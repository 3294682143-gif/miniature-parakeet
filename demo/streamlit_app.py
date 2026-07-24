from __future__ import annotations

import re
import sys
from collections import deque
from itertools import islice
from pathlib import Path
from threading import Lock, RLock
from time import monotonic as _monotonic
from time import time as _wall_time
from typing import Any, cast
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import streamlit as st

from math_agent.harness.demo_adapter import (
    build_demo_budget_preview,
    build_demo_timeline,
    build_mock_voting_demo,
    load_demo_memory_summary,
    load_demo_skill_summary,
    result_to_display_dict,
    safe_get_risk_flags,
    safe_get_tool_calls,
)
from math_agent.harness.replay import (
    build_timeline,
    render_replay_markdown,
    summarize_trace,
)
from math_agent.harness.trace_reader import read_trace
from math_agent.pipeline import MathAgentPipeline

DEMO_TRACE_ROOT = (
    Path(__file__).resolve().parent.parent / "outputs" / "demo_traces"
).resolve()
_SESSION_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_TRACE_ID_PATTERN = re.compile(r"demo_[0-9a-f]{32}")
_SESSION_STATE_KEY = "_demo_session_id"
_TRACE_LIST_LIMIT = 100
_TRACE_DIRECTORY_SCAN_LIMIT = 128
_TRACE_ROOT_SCAN_LIMIT = 128
_DEMO_SESSION_TRACE_LIMIT = 50
_DEMO_SESSION_BYTE_LIMIT = 8 * 1024 * 1024
_DEMO_TRACE_BYTE_LIMIT = 512 * 1024
_DEMO_GLOBAL_SESSION_LIMIT = 64
_DEMO_GLOBAL_TRACE_LIMIT = 512
_DEMO_GLOBAL_BYTE_LIMIT = 64 * 1024 * 1024
_DEMO_TRACE_TTL_SECONDS = 60 * 60.0
_DEMO_QUESTION_CHARACTER_LIMIT = 8_192
_DEMO_QUESTION_UTF8_BYTE_LIMIT = 32 * 1024
_DEMO_MIN_SOLVE_INTERVAL_SECONDS = 2.0
_DEMO_GLOBAL_SOLVE_WINDOW_SECONDS = 60.0
_DEMO_GLOBAL_SOLVE_LIMIT = 30
_DEMO_NEW_SESSION_WINDOW_SECONDS = 60 * 60.0
_DEMO_NEW_SESSION_LIMIT = 16
_DEMO_ACTIVE_SESSION_LIMIT = 32
_ADMITTED_SESSION_TTL_SECONDS = 60 * 60.0
_RATE_LIMIT_STATE_TTL_SECONDS = 60 * 60.0
_RATE_LIMIT_STATE_LIMIT = 4096
_RATE_LIMIT_LOCK = Lock()
_TRACE_BUDGET_LOCK = RLock()
_LAST_SOLVE_AT: dict[str, float] = {}
_GLOBAL_SOLVE_TIMES: deque[float] = deque()
_NEW_SESSION_TIMES: deque[float] = deque()
_ADMITTED_SESSION_AT: dict[str, float] = {}
_GLOBAL_TRACE_RESERVATIONS: dict[str, str] = {}

_TraceEntry = tuple[Path, str, float, int]
_SessionEntry = tuple[Path, list[_TraceEntry]]


class DemoTraceBudgetError(RuntimeError):
    """Raised when server-owned Demo trace storage cannot stay within budget."""


class DemoRateLimitError(RuntimeError):
    """Raised when one Demo session submits solve requests too quickly."""


class DemoInputError(ValueError):
    """Raised when untrusted Demo input exceeds a server-owned boundary."""


def _trace_root() -> Path:
    if DEMO_TRACE_ROOT.is_symlink():
        raise DemoTraceBudgetError("Demo trace root must not be a symbolic link")
    return DEMO_TRACE_ROOT.resolve()


def _session_trace_dir(session_id: str) -> Path:
    """Return the server-owned trace directory for one Streamlit session."""
    if _SESSION_ID_PATTERN.fullmatch(session_id) is None:
        raise ValueError("invalid demo session ID")
    root = _trace_root()
    trace_dir = (root / session_id).resolve()
    if trace_dir.parent != root:
        raise ValueError("demo session directory escapes the trace root")
    return trace_dir


def _get_or_create_session_id() -> str:
    session_id = st.session_state.get(_SESSION_STATE_KEY)
    if (
        not isinstance(session_id, str)
        or _SESSION_ID_PATTERN.fullmatch(session_id) is None
    ):
        session_id = uuid4().hex
        st.session_state[_SESSION_STATE_KEY] = session_id
    return session_id


def _new_trace_id(trace_dir: Path) -> str:
    for _ in range(4):
        trace_id = f"demo_{uuid4().hex}"
        if (
            trace_id not in _GLOBAL_TRACE_RESERVATIONS
            and not (trace_dir / f"{trace_id}.json").exists()
        ):
            return trace_id
    raise RuntimeError("could not allocate a unique demo trace ID")


def _validate_trace_budget() -> None:
    if _TRACE_DIRECTORY_SCAN_LIMIT < 1:
        raise DemoTraceBudgetError("invalid trace directory scan limit")
    if _TRACE_ROOT_SCAN_LIMIT < 1:
        raise DemoTraceBudgetError("invalid trace root scan limit")
    if _DEMO_SESSION_TRACE_LIMIT < 1:
        raise DemoTraceBudgetError("invalid session trace count limit")
    if _DEMO_TRACE_BYTE_LIMIT < 1:
        raise DemoTraceBudgetError("invalid per-trace byte limit")
    if _DEMO_SESSION_BYTE_LIMIT < _DEMO_TRACE_BYTE_LIMIT:
        raise DemoTraceBudgetError("invalid session trace byte limit")
    if _DEMO_GLOBAL_SESSION_LIMIT < 1:
        raise DemoTraceBudgetError("invalid global session limit")
    if _DEMO_GLOBAL_TRACE_LIMIT < 1:
        raise DemoTraceBudgetError("invalid global trace limit")
    if _DEMO_GLOBAL_BYTE_LIMIT < _DEMO_TRACE_BYTE_LIMIT:
        raise DemoTraceBudgetError("invalid global trace byte limit")
    if _DEMO_TRACE_TTL_SECONDS <= 0:
        raise DemoTraceBudgetError("invalid trace TTL")


def _remove_trace(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise DemoTraceBudgetError("could not enforce the Demo trace budget") from exc


def _bounded_directory_entries(trace_dir: Path) -> list[Path]:
    """Read at most the fixed scan budget; never sort an unbounded iterator."""
    try:
        candidates = list(islice(trace_dir.iterdir(), _TRACE_DIRECTORY_SCAN_LIMIT + 1))
    except OSError as exc:
        raise DemoTraceBudgetError("could not enumerate Demo traces") from exc
    if len(candidates) > _TRACE_DIRECTORY_SCAN_LIMIT:
        raise DemoTraceBudgetError("Demo trace directory has too many entries")
    return candidates


def _bounded_root_entries(root: Path) -> list[Path]:
    """Read at most the fixed root budget without following child links."""
    try:
        candidates = list(islice(root.iterdir(), _TRACE_ROOT_SCAN_LIMIT + 1))
    except OSError as exc:
        raise DemoTraceBudgetError("could not enumerate the Demo trace root") from exc
    if len(candidates) > _TRACE_ROOT_SCAN_LIMIT:
        raise DemoTraceBudgetError("Demo trace root has too many entries")
    return candidates


def _load_trace_entries(
    trace_dir: Path, *, now: float, reject_unmanaged: bool = False
) -> list[_TraceEntry]:
    entries: list[_TraceEntry] = []
    for candidate in _bounded_directory_entries(trace_dir):
        try:
            if candidate.is_symlink():
                if reject_unmanaged:
                    raise DemoTraceBudgetError(
                        "Demo trace directory contains a symbolic link"
                    )
                continue
            if not candidate.is_file():
                if reject_unmanaged:
                    raise DemoTraceBudgetError(
                        "Demo trace directory contains an unmanaged entry"
                    )
                continue
            if candidate.resolve().parent != trace_dir:
                if reject_unmanaged:
                    raise DemoTraceBudgetError("Demo trace escapes its session root")
                continue
            if _TRACE_ID_PATTERN.fullmatch(candidate.stem) is None:
                if reject_unmanaged:
                    raise DemoTraceBudgetError(
                        "Demo trace directory contains an unmanaged file"
                    )
                continue
            stat = candidate.stat()
        except OSError as exc:
            raise DemoTraceBudgetError("could not inspect a Demo trace") from exc

        if now - stat.st_mtime > _DEMO_TRACE_TTL_SECONDS:
            _remove_trace(candidate)
            continue
        if stat.st_size > _DEMO_TRACE_BYTE_LIMIT:
            _remove_trace(candidate)
            continue
        entries.append((candidate, candidate.stem, stat.st_mtime, stat.st_size))

    entries.sort(key=lambda entry: (entry[2], entry[1]), reverse=True)
    return entries


def _prune_trace_entries(
    entries: list[_TraceEntry], *, kept_count: int, kept_bytes: int
) -> list[_TraceEntry]:
    kept = list(entries)
    total_bytes = sum(entry[3] for entry in kept)
    while len(kept) > kept_count or total_bytes > kept_bytes:
        victim = kept.pop()
        _remove_trace(victim[0])
        total_bytes -= victim[3]
    return kept


def _load_global_trace_state(*, now: float) -> dict[str, _SessionEntry]:
    root = _trace_root()
    if not root.exists():
        return {}
    if not root.is_dir():
        raise DemoTraceBudgetError("Demo trace root is not a directory")

    sessions: dict[str, _SessionEntry] = {}
    pending_sessions = set(_GLOBAL_TRACE_RESERVATIONS.values())
    for candidate in _bounded_root_entries(root):
        if candidate.is_symlink():
            raise DemoTraceBudgetError("Demo trace root contains a symbolic link")
        if _SESSION_ID_PATTERN.fullmatch(candidate.name) is None:
            raise DemoTraceBudgetError("Demo trace root contains an unmanaged entry")
        try:
            if candidate.resolve().parent != root or not candidate.is_dir():
                raise DemoTraceBudgetError(
                    "Demo session directory escapes the fixed trace root"
                )
        except OSError as exc:
            raise DemoTraceBudgetError(
                "could not inspect a Demo session directory"
            ) from exc

        entries = _load_trace_entries(candidate, now=now, reject_unmanaged=True)
        entries = _prune_trace_entries(
            entries,
            kept_count=_DEMO_SESSION_TRACE_LIMIT,
            kept_bytes=_DEMO_SESSION_BYTE_LIMIT,
        )
        if not entries and candidate.name not in pending_sessions:
            try:
                candidate.rmdir()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise DemoTraceBudgetError(
                    "could not remove an expired Demo session"
                ) from exc
            continue
        sessions[candidate.name] = (candidate, entries)
    return sessions


def _global_trace_totals(sessions: dict[str, _SessionEntry]) -> tuple[int, int]:
    entries = [
        entry
        for _trace_dir, session_entries in sessions.values()
        for entry in session_entries
    ]
    return len(entries), sum(entry[3] for entry in entries)


def _maintain_session_trace_budget(
    session_id: str,
    *,
    reserve_new_trace: bool,
    now: float | None = None,
) -> list[_TraceEntry]:
    """Expire and prune session traces while keeping all work server-bounded."""
    with _TRACE_BUDGET_LOCK:
        _validate_trace_budget()
        trace_dir = _session_trace_dir(session_id)
        if not trace_dir.is_dir():
            return []

        entries = _load_trace_entries(
            trace_dir, now=_wall_time() if now is None else now
        )
        kept_count = _DEMO_SESSION_TRACE_LIMIT - int(reserve_new_trace)
        kept_bytes = _DEMO_SESSION_BYTE_LIMIT - (
            _DEMO_TRACE_BYTE_LIMIT if reserve_new_trace else 0
        )
        return _prune_trace_entries(
            entries, kept_count=kept_count, kept_bytes=kept_bytes
        )


def _prepare_new_trace(session_id: str) -> tuple[Path, str, Path]:
    """Reserve one bounded global trace slot before running the pipeline."""
    with _TRACE_BUDGET_LOCK:
        _validate_trace_budget()
        trace_dir = _session_trace_dir(session_id)
        sessions = _load_global_trace_state(now=_wall_time())

        if session_id in _GLOBAL_TRACE_RESERVATIONS.values():
            raise DemoTraceBudgetError(
                "this Demo session already has a solve in progress"
            )
        if session_id not in sessions and len(sessions) >= _DEMO_GLOBAL_SESSION_LIMIT:
            raise DemoTraceBudgetError("Demo global session limit reached")

        current = sessions.get(session_id)
        if current is not None:
            current_entries = _prune_trace_entries(
                current[1],
                kept_count=_DEMO_SESSION_TRACE_LIMIT - 1,
                kept_bytes=_DEMO_SESSION_BYTE_LIMIT - _DEMO_TRACE_BYTE_LIMIT,
            )
            sessions[session_id] = (current[0], current_entries)

        trace_count, trace_bytes = _global_trace_totals(sessions)
        pending_count = len(_GLOBAL_TRACE_RESERVATIONS)
        if trace_count + pending_count + 1 > _DEMO_GLOBAL_TRACE_LIMIT:
            raise DemoTraceBudgetError("Demo global trace limit reached")
        if (
            trace_bytes + (pending_count + 1) * _DEMO_TRACE_BYTE_LIMIT
            > _DEMO_GLOBAL_BYTE_LIMIT
        ):
            raise DemoTraceBudgetError("Demo global byte limit reached")

        trace_dir_was_missing = not trace_dir.exists()
        try:
            trace_dir.mkdir(parents=True, exist_ok=True)
            question_id = _new_trace_id(trace_dir)
            trace_path = trace_dir / f"{question_id}.json"
            _GLOBAL_TRACE_RESERVATIONS[question_id] = session_id
        except (OSError, RuntimeError) as exc:
            if trace_dir_was_missing:
                try:
                    trace_dir.rmdir()
                except OSError:
                    pass
            raise DemoTraceBudgetError("could not reserve Demo trace storage") from exc
        return trace_dir, question_id, trace_path


def _abort_new_trace(session_id: str, trace_path: Path) -> None:
    with _TRACE_BUDGET_LOCK:
        _GLOBAL_TRACE_RESERVATIONS.pop(trace_path.stem, None)
        _remove_trace(trace_path)
        trace_dir = _session_trace_dir(session_id)
        try:
            trace_dir.rmdir()
        except OSError:
            pass


def _validate_demo_question(question: str) -> None:
    if _DEMO_QUESTION_CHARACTER_LIMIT < 1:
        raise DemoInputError("invalid Demo question character limit")
    if _DEMO_QUESTION_UTF8_BYTE_LIMIT < 1:
        raise DemoInputError("invalid Demo question UTF-8 byte limit")
    if not isinstance(question, str):
        raise DemoInputError("Demo question must be text")
    if len(question) > _DEMO_QUESTION_CHARACTER_LIMIT:
        raise DemoInputError("Demo question exceeds the character limit")
    try:
        question_bytes = question.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise DemoInputError("Demo question is not valid UTF-8 text") from exc
    if len(question_bytes) > _DEMO_QUESTION_UTF8_BYTE_LIMIT:
        raise DemoInputError("Demo question exceeds the UTF-8 byte limit")


def _expire_timestamps(
    timestamps: deque[float], *, now: float, window_seconds: float
) -> None:
    stale_at_or_before = now - window_seconds
    while timestamps and timestamps[0] <= stale_at_or_before:
        timestamps.popleft()


def _validate_rate_limit_budget() -> None:
    if _DEMO_MIN_SOLVE_INTERVAL_SECONDS < 0:
        raise DemoRateLimitError("invalid Demo solve interval")
    if _DEMO_GLOBAL_SOLVE_WINDOW_SECONDS <= 0 or _DEMO_GLOBAL_SOLVE_LIMIT < 1:
        raise DemoRateLimitError("invalid Demo global solve-rate budget")
    if _DEMO_NEW_SESSION_WINDOW_SECONDS <= 0 or _DEMO_NEW_SESSION_LIMIT < 1:
        raise DemoRateLimitError("invalid Demo new-session rate budget")
    if _DEMO_ACTIVE_SESSION_LIMIT < 1 or _ADMITTED_SESSION_TTL_SECONDS <= 0:
        raise DemoRateLimitError("invalid Demo active-session budget")
    if _RATE_LIMIT_STATE_TTL_SECONDS <= 0 or _RATE_LIMIT_STATE_LIMIT < 1:
        raise DemoRateLimitError("invalid Demo rate-limit state budget")


def _prune_rate_limit_state(*, now: float) -> None:
    _expire_timestamps(
        _GLOBAL_SOLVE_TIMES,
        now=now,
        window_seconds=_DEMO_GLOBAL_SOLVE_WINDOW_SECONDS,
    )
    _expire_timestamps(
        _NEW_SESSION_TIMES,
        now=now,
        window_seconds=_DEMO_NEW_SESSION_WINDOW_SECONDS,
    )

    solve_stale_at_or_before = now - _RATE_LIMIT_STATE_TTL_SECONDS
    stale_solve_sessions = [
        key
        for key, last_solve in _LAST_SOLVE_AT.items()
        if last_solve <= solve_stale_at_or_before
    ]
    for key in stale_solve_sessions:
        del _LAST_SOLVE_AT[key]

    admission_stale_at_or_before = now - _ADMITTED_SESSION_TTL_SECONDS
    stale_admissions = [
        key
        for key, last_seen in _ADMITTED_SESSION_AT.items()
        if last_seen <= admission_stale_at_or_before
    ]
    for key in stale_admissions:
        del _ADMITTED_SESSION_AT[key]


def _claim_solve_slot(session_id: str) -> None:
    _validate_rate_limit_budget()
    now = _monotonic()
    with _RATE_LIMIT_LOCK:
        _prune_rate_limit_state(now=now)

        previous = _LAST_SOLVE_AT.get(session_id)
        if previous is not None and now - previous < _DEMO_MIN_SOLVE_INTERVAL_SECONDS:
            raise DemoRateLimitError("Demo solve requests arrived too quickly")
        if len(_GLOBAL_SOLVE_TIMES) >= _DEMO_GLOBAL_SOLVE_LIMIT:
            raise DemoRateLimitError("Demo global solve rate limit reached")

        is_new_session = session_id not in _ADMITTED_SESSION_AT
        if is_new_session:
            if len(_ADMITTED_SESSION_AT) >= _DEMO_ACTIVE_SESSION_LIMIT:
                raise DemoRateLimitError("Demo active session limit reached")
            if len(_NEW_SESSION_TIMES) >= _DEMO_NEW_SESSION_LIMIT:
                raise DemoRateLimitError("Demo new session rate limit reached")
        if previous is None and len(_LAST_SOLVE_AT) >= _RATE_LIMIT_STATE_LIMIT:
            raise DemoRateLimitError("Demo rate-limit state is at capacity")

        _GLOBAL_SOLVE_TIMES.append(now)
        if is_new_session:
            _NEW_SESSION_TIMES.append(now)
        _ADMITTED_SESSION_AT[session_id] = now
        _LAST_SOLVE_AT[session_id] = now


def _finalize_new_trace(session_id: str, trace_path: Path) -> None:
    with _TRACE_BUDGET_LOCK:
        if _GLOBAL_TRACE_RESERVATIONS.get(trace_path.stem) != session_id:
            raise DemoTraceBudgetError("Demo trace reservation is missing")
        del _GLOBAL_TRACE_RESERVATIONS[trace_path.stem]
        trace_dir = _session_trace_dir(session_id)
        try:
            if (
                trace_path.is_symlink()
                or not trace_path.is_file()
                or trace_path.resolve().parent != trace_dir
            ):
                raise DemoTraceBudgetError("Demo pipeline did not create a valid trace")
            trace_bytes = trace_path.stat().st_size
        except OSError as exc:
            raise DemoTraceBudgetError("could not inspect the new Demo trace") from exc

        if trace_bytes > _DEMO_TRACE_BYTE_LIMIT:
            _remove_trace(trace_path)
            raise DemoTraceBudgetError("new Demo trace exceeds the byte limit")

        entries = _maintain_session_trace_budget(session_id, reserve_new_trace=False)
        if trace_path.stem not in {entry[1] for entry in entries}:
            _remove_trace(trace_path)
            raise DemoTraceBudgetError("new Demo trace exceeds the session byte limit")

        sessions = _load_global_trace_state(now=_wall_time())
        trace_count, trace_total_bytes = _global_trace_totals(sessions)
        pending_count = len(_GLOBAL_TRACE_RESERVATIONS)
        if trace_count + pending_count > _DEMO_GLOBAL_TRACE_LIMIT:
            _remove_trace(trace_path)
            raise DemoTraceBudgetError("Demo global trace limit reached")
        if (
            trace_total_bytes + pending_count * _DEMO_TRACE_BYTE_LIMIT
            > _DEMO_GLOBAL_BYTE_LIMIT
        ):
            _remove_trace(trace_path)
            raise DemoTraceBudgetError("Demo global byte limit reached")


def list_session_trace_ids(session_id: str) -> list[str]:
    """Enumerate replayable trace IDs from this session, never client paths."""
    entries = _maintain_session_trace_budget(session_id, reserve_new_trace=False)
    return [entry[1] for entry in entries[:_TRACE_LIST_LIMIT]]


def read_session_trace(session_id: str, trace_id: str) -> dict[str, Any]:
    """Read only a trace ID previously enumerated in this server session."""
    if _TRACE_ID_PATTERN.fullmatch(trace_id) is None:
        raise ValueError("invalid demo trace ID")
    if trace_id not in set(list_session_trace_ids(session_id)):
        raise ValueError("demo trace ID is not available in this session")

    trace_dir = _session_trace_dir(session_id)
    candidate = trace_dir / f"{trace_id}.json"
    if candidate.is_symlink() or candidate.resolve().parent != trace_dir:
        raise ValueError("invalid demo trace ID")
    return read_trace(candidate)


def run_demo_pipeline(
    question: str,
    *,
    session_id: str,
    enable_tools: bool,
    max_refine_rounds: int,
    mode: str,
):
    _validate_demo_question(question)
    _session_trace_dir(session_id)
    _claim_solve_slot(session_id)
    trace_dir, question_id, trace_path = _prepare_new_trace(session_id)
    try:
        pipeline = MathAgentPipeline(
            mock=True,
            enable_tools=enable_tools,
            save_trace=True,
            trace_dir=trace_dir,
            max_refine_rounds=max_refine_rounds,
            run_mode=mode,
        )
        route_info = pipeline.router.route(question)
        result = pipeline.solve(question=question, question_id=question_id)
        _finalize_new_trace(session_id, trace_path)
    except Exception:
        _abort_new_trace(session_id, trace_path)
        raise
    return result, trace_path, route_info


def main() -> None:
    st.set_page_config(page_title="EvoExternMath-S1++ 数学智能体 Demo", layout="wide")
    st.title("EvoExternMath-S1++ 数学智能体 Demo")
    session_id = _get_or_create_session_id()

    with st.sidebar:
        st.caption("local preview · run mode fixed to mock")
        enable_tools = st.toggle("enable_tools", value=False)
        mode = st.selectbox("mode", ["full", "fast", "tool-first"], index=0)
        max_refine_rounds = int(
            st.number_input(
                "max_refine_rounds", min_value=0, max_value=3, value=1, step=1
            )
        )
        show_raw_json = st.toggle("show raw json", value=False)
        replay_existing_trace = st.toggle("replay existing trace", value=False)
        st.caption("read-only skill viewer")
        st.caption("read-only memory summary")
        st.caption("read-only budget preview")

    st.header("A. Input Panel")
    st.caption(
        "question limit: "
        f"{_DEMO_QUESTION_CHARACTER_LIMIT:,} characters / "
        f"{_DEMO_QUESTION_UTF8_BYTE_LIMIT:,} UTF-8 bytes"
    )
    question = st.text_area(
        "question",
        value="计算 2+3",
        height=120,
        max_chars=_DEMO_QUESTION_CHARACTER_LIMIT,
    )

    result = None
    route_info = None
    if st.button("开始求解", type="primary"):
        try:
            result, _, route_info = run_demo_pipeline(
                question,
                session_id=session_id,
                enable_tools=enable_tools,
                max_refine_rounds=max_refine_rounds,
                mode=mode,
            )
        except (DemoInputError, DemoRateLimitError, DemoTraceBudgetError) as exc:
            st.warning(str(exc))

    if result is not None:
        display = result_to_display_dict(result)
        st.header("B. Result Panel")
        st.write("final_answer:", display["final_answer"])
        st.write("status:", display["status"])
        st.write("confidence:", display["confidence"])
        st.write(
            "verification:",
            f"{display['verification_method']} / passed={display['verification_passed']}",
        )
        st.write("risk flags:", safe_get_risk_flags(result) or [])

        st.header("C. Agent Timeline")
        for row in build_demo_timeline(result):
            st.write(f"{row['stage']} → {row['status']} ({row['detail']})")

        st.header("D. Tool Calls")
        tool_calls = safe_get_tool_calls(result)
        if not tool_calls:
            st.info("No tool calls recorded")
        else:
            st.json(tool_calls, expanded=False)

        st.header("E. Skill Library Viewer")
        skill_summary = load_demo_skill_summary(question, route_info)
        st.write("list_skills:", skill_summary.get("skills", []))
        st.write("select_skill:", skill_summary.get("selected_skill"))
        st.json(skill_summary.get("selected_skill_meta") or {}, expanded=False)

        st.header("F. Memory Summary")
        memory_summary = load_demo_memory_summary()
        st.json(memory_summary.get("summary", {}), expanded=False)

        st.header("G. Budget Preview")
        st.json(
            build_demo_budget_preview(question, route_info=route_info, mode=mode),
            expanded=False,
        )

        st.header("H. Weighted Voting Explainer")
        st.markdown(
            "- verifier-gated，不是裸 majority vote\n- 默认不接入主流程\n- 后续可用于 candidate solver"
        )
        st.json(build_mock_voting_demo(), expanded=False)

    st.header("I. Trace Replay Panel")
    try:
        trace_ids = list_session_trace_ids(session_id)
    except DemoTraceBudgetError as exc:
        st.warning(str(exc))
        trace_ids = []
    if not trace_ids:
        st.info("No traces are available in this preview session")
    else:
        selected_trace_id = st.selectbox("trace ID", trace_ids, index=0)
        if replay_existing_trace:
            try:
                trace_read = read_session_trace(session_id, selected_trace_id)
            except (ValueError, DemoTraceBudgetError) as exc:
                st.warning(str(exc))
            else:
                if not trace_read.get("ok"):
                    st.warning(str(trace_read.get("error")))
                else:
                    trace_value = trace_read.get("trace")
                    if not isinstance(trace_value, dict):
                        st.warning("trace payload is not a JSON object")
                    else:
                        trace = cast(dict[str, Any], trace_value)
                        st.write(build_timeline(trace))
                        st.write(summarize_trace(trace))
                        st.markdown(render_replay_markdown(trace))

    if result is not None and show_raw_json:
        st.header("J. Raw JSON")
        st.json(result.model_dump(), expanded=False)


if __name__ == "__main__":
    main()
