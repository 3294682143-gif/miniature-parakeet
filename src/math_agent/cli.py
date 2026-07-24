from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from .clients.interns1_client import InternS1Client
from .control.hard_mode import build_hard_mode_policy
from .harness.trace_reader import (
    read_trace_dir,
    read_trusted_program_trace,
)
from .io_utils import (
    iter_bounded_utf8_lines,
    load_bounded_jsonl,
    path_is_within,
    paths_alias,
    strict_json_loads,
)
from .logging_utils import (
    atomic_text_write,
    ensure_dir,
    safe_text_write,
    trace_path_for_question,
    write_trace,
)
from .pipeline import execution_fingerprint_for_question, solve_question
from .schemas import (
    MathQuestion,
    SolveResult,
    is_semantically_successful,
    is_valid_trace_audit_evidence,
    make_failure_result,
    question_fingerprint,
)
from .security import path_has_link_component, safe_exception_text

_RETRY_STATUSES = {"fail", "partial"}
MAX_BATCH_INPUT_BYTES = 16 * 1024 * 1024
MAX_BATCH_LINE_CHARS = 64 * 1024
MAX_BATCH_ROWS = 100_000
MAX_REAL_BATCH_ROWS = 1_000
MAX_BATCH_RESULT_LINE_BYTES = 1 * 1024 * 1024
MAX_BATCH_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_BATCH_TRACE_BYTES = 64 * 1024 * 1024


def _validate_real_mode_or_raise(real: bool) -> None:
    if not real:
        return
    InternS1Client(mock=False)._validate_real_mode_config()


def _paths_alias(first: Path, second: Path) -> bool:
    return paths_alias(first, second)


def _path_is_within(path: Path, directory: Path) -> bool:
    return path_is_within(path, directory)


def _load_resume_rows(
    output_path: Path, retry_failed: bool
) -> tuple[list[str], set[str], set[str], dict[str, SolveResult]]:
    if not output_path.exists():
        return [], set(), set(), {}
    kept_lines: list[str] = []
    skip_ids: set[str] = set()
    retry_ids: set[str] = set()
    kept_results: dict[str, SolveResult] = {}
    rows, _ = load_bounded_jsonl(
        output_path,
        require_objects=True,
        require_single_link=True,
        max_bytes=MAX_BATCH_OUTPUT_BYTES,
        max_line_bytes=MAX_BATCH_RESULT_LINE_BYTES,
        max_rows=MAX_BATCH_ROWS,
    )
    for raw in rows:
        try:
            row = SolveResult.model_validate(raw)
        except Exception as exc:
            raw_qid = raw.get("question_id") if isinstance(raw, dict) else None
            if (
                retry_failed
                and isinstance(raw_qid, str)
                and raw_qid.strip() == raw_qid
                and 1 <= len(raw_qid) <= 128
                and raw_qid not in skip_ids
                and raw_qid not in retry_ids
            ):
                retry_ids.add(raw_qid)
                continue
            raise ValueError("resume output contains an invalid result row") from exc
        qid = row.question_id
        if qid in skip_ids or qid in retry_ids:
            raise ValueError("resume output contains duplicate question_id values")
        status = row.status
        invalid_success = status == "success" and not is_semantically_successful(row)
        if invalid_success:
            if retry_failed:
                retry_ids.add(qid)
                continue
            raise ValueError("resume output contains an inconsistent success row")
        if retry_failed and status in _RETRY_STATUSES:
            retry_ids.add(qid)
            continue
        kept_lines.append(row.model_dump_json(ensure_ascii=False))
        skip_ids.add(qid)
        kept_results[qid] = row
    return kept_lines, skip_ids, retry_ids, kept_results


def _failure_question_id(raw: object, line_index: int) -> str:
    fallback = f"line_{line_index}"
    qid = (
        str(raw.get("question_id", fallback)) if isinstance(raw, dict) else fallback
    ).strip()
    return qid if qid and len(qid) <= 128 else fallback


def _reject_duplicate_batch_ids(input_lines: list[tuple[int, str]]) -> set[str]:
    seen: set[str] = set()
    for line_number, line in input_lines:
        if not line.strip():
            continue
        raw: object = {}
        try:
            raw = strict_json_loads(line)
            qid = MathQuestion.model_validate(raw).question_id
        except Exception:
            qid = _failure_question_id(raw, line_number - 1)
        if qid in seen:
            raise ValueError("batch input contains duplicate question_id values")
        seen.add(qid)
    return seen


def _read_trace_budget(trace_dir: str | Path, question_id: str) -> dict[str, int]:
    trace_path = trace_path_for_question(trace_dir, question_id)
    if not trace_path.exists():
        return {
            "model_calls": 0,
            "tool_calls": 0,
            "trace_found": 0,
            "file_bytes": 0,
        }
    loaded = read_trusted_program_trace(trace_path)
    if loaded.get("ok") is not True or not isinstance(loaded.get("trace"), dict):
        raise ValueError("trace output is unreadable or unsafe")
    trace = loaded["trace"]
    file_bytes = loaded.get("file_bytes")
    if (
        isinstance(file_bytes, bool)
        or not isinstance(file_bytes, int)
        or file_bytes < 0
    ):
        raise ValueError("trace output metadata is unreadable")
    model_calls = trace.get("model_calls", [])
    tool_calls = trace.get("tool_calls", [])
    return {
        "model_calls": len(model_calls) if isinstance(model_calls, list) else 0,
        "tool_calls": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "trace_found": 1,
        "file_bytes": file_bytes,
    }


def _resume_trace_matches(
    trace_dir: str | Path,
    question: MathQuestion,
    prior: SolveResult,
    *,
    real_mode: bool,
) -> bool:
    trace_path = trace_path_for_question(trace_dir, question.question_id)
    if not trace_path.exists():
        return False
    loaded = read_trusted_program_trace(trace_path)
    trace = loaded.get("trace")
    if loaded.get("ok") is not True or not isinstance(trace, dict):
        return False
    final_result = trace.get("final_result")
    if (
        not isinstance(final_result, dict)
        or not isinstance(trace.get("route_info"), dict)
        or not isinstance(trace.get("verifier_result"), dict)
        or not isinstance(trace.get("started_at"), str)
        or not trace.get("started_at")
        or not isinstance(trace.get("finished_at"), str)
        or not trace.get("finished_at")
        or isinstance(trace.get("latency_seconds"), bool)
        or not isinstance(trace.get("latency_seconds"), (int, float))
        or float(trace.get("latency_seconds", -1)) < 0.0
        or not isinstance(trace.get("prompt_version"), str)
        or not isinstance(trace.get("run_mode"), str)
    ):
        return False
    return trace.get("question") == question.question and is_valid_trace_audit_evidence(
        trace,
        prior,
        expected_real_mode=real_mode,
    )


def _existing_trace_bytes(trace_dir: Path) -> int:
    state = read_trace_dir(trace_dir)
    if state.get("ok") is not True:
        raise ValueError("trace directory is unreadable or unsafe")
    total = 0
    for item in state.get("items", []):
        if not isinstance(item, dict) or item.get("ok") is not True:
            raise ValueError("trace directory contains an unsafe trace")
        file_bytes = item.get("file_bytes")
        if (
            isinstance(file_bytes, bool)
            or not isinstance(file_bytes, int)
            or file_bytes < 0
        ):
            raise ValueError("trace metadata is unreadable")
        total += file_bytes
    if total > MAX_BATCH_TRACE_BYTES:
        raise ValueError("trace directory exceeds the batch byte budget")
    return total


def _int_stat(stats: dict[str, object], key: str) -> int:
    value = stats.get(key, 0)
    return value if isinstance(value, int) else 0


def _float_stat(stats: dict[str, object], key: str) -> float:
    value = stats.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def cmd_solve(args: argparse.Namespace) -> int:
    _validate_real_mode_or_raise(args.real)
    hard_mode_policy = None
    if args.hard_mode:
        hard_mode_policy = build_hard_mode_policy(
            enabled=True, level=args.hard_mode_level
        )
    result = solve_question(
        MathQuestion(question=args.question, question_id=args.question_id),
        mock=not args.real,
        enable_tools=args.enable_tools,
        save_trace=not args.no_trace,
        trace_dir=args.trace_dir,
        run_mode=args.mode,
        hard_mode_policy=hard_mode_policy,
    )
    print(result.model_dump_json(ensure_ascii=False))
    return (
        1 if args.fail_on_non_success and not is_semantically_successful(result) else 0
    )


def cmd_batch(args: argparse.Namespace) -> int:
    _validate_real_mode_or_raise(args.real)
    input_path = Path(args.input).absolute()
    output_path = Path(args.output).absolute()
    stats_path = Path(args.stats).absolute() if args.stats else None
    if path_has_link_component(input_path):
        raise ValueError("batch input path contains a link or junction")
    ensure_dir(output_path.parent)
    if path_has_link_component(output_path):
        raise ValueError("batch output path contains a link or junction")
    if stats_path is not None:
        ensure_dir(stats_path.parent)
        if path_has_link_component(stats_path):
            raise ValueError("batch stats path contains a link or junction")
    if _paths_alias(input_path, output_path) or (
        stats_path is not None
        and (
            _paths_alias(input_path, stats_path)
            or _paths_alias(output_path, stats_path)
        )
    ):
        raise ValueError("batch input, output, and stats paths must be distinct")
    if not args.no_trace:
        trace_root = ensure_dir(args.trace_dir)
        protected_paths = [input_path, output_path]
        if stats_path is not None:
            protected_paths.append(stats_path)
        if any(_path_is_within(path, trace_root) for path in protected_paths):
            raise ValueError("batch input, output, and stats must be outside trace_dir")
    try:
        input_size = input_path.stat().st_size
    except OSError as exc:
        raise ValueError("batch input is unreadable") from exc
    if input_size > MAX_BATCH_INPUT_BYTES:
        raise ValueError("batch input exceeds the size limit")
    row_limit = MAX_REAL_BATCH_ROWS if args.real else MAX_BATCH_ROWS
    input_lines = list(
        iter_bounded_utf8_lines(
            input_path,
            max_bytes=MAX_BATCH_INPUT_BYTES,
            max_line_bytes=MAX_BATCH_LINE_CHARS,
            max_rows=MAX_BATCH_ROWS,
        )
    )
    input_ids = _reject_duplicate_batch_ids(input_lines)
    kept_lines: list[str] = []
    skip_ids: set[str] = set()
    retry_ids: set[str] = set()
    kept_results: dict[str, SolveResult] = {}
    if args.resume:
        kept_lines, skip_ids, retry_ids, kept_results = _load_resume_rows(
            output_path, args.retry_failed
        )
        for stale_id in sorted(skip_ids - input_ids):
            stale_line = kept_results[stale_id].model_dump_json(ensure_ascii=False)
            kept_lines.remove(stale_line)
            skip_ids.remove(stale_id)
            kept_results.pop(stale_id)
        retry_ids.intersection_update(input_ids)
    output_lines = list(kept_lines)
    output_bytes = sum(len((line + "\n").encode("utf-8")) for line in output_lines)
    if output_bytes > MAX_BATCH_OUTPUT_BYTES:
        raise ValueError("resume output exceeds the batch byte budget")
    trace_bytes = (
        _existing_trace_bytes(Path(args.trace_dir).absolute())
        if not args.no_trace
        else 0
    )
    batch_started = time.perf_counter()
    stats: dict[str, object] = {
        "input": str(input_path),
        "output": str(output_path),
        "mode": args.mode,
        "real": bool(args.real),
        "enable_tools": bool(args.enable_tools),
        "trace_dir": str(args.trace_dir),
        "resume": bool(args.resume),
        "retry_failed": bool(args.retry_failed),
        "input_count": 0,
        "processed_count": 0,
        "skipped_count": 0,
        "retry_failed_count": len(retry_ids),
        "kept_existing_count": len(kept_lines),
        "error_count": 0,
        "status_counts": {},
        "total_elapsed_seconds": 0.0,
        "average_elapsed_seconds": 0.0,
        "total_model_calls": 0,
        "total_tool_calls": 0,
        "trace_found_count": 0,
        "trace_bytes": trace_bytes,
    }
    status_counts: dict[str, int] = {}
    for line_number, line in input_lines:
        idx = line_number - 1
        if idx >= row_limit:
            raise ValueError("batch input exceeds the active row limit")
        if not line.strip():
            continue
        stats["input_count"] = _int_stat(stats, "input_count") + 1
        raw = {}
        try:
            raw = strict_json_loads(line)
            q = MathQuestion.model_validate(raw)
            if q.question_id in skip_ids:
                prior = kept_results[q.question_id]
                expected_execution_fingerprint = execution_fingerprint_for_question(
                    q,
                    mock=not args.real,
                    enable_tools=args.enable_tools,
                    save_trace=not args.no_trace,
                    trace_dir=args.trace_dir,
                    run_mode=args.mode,
                )
                trace_matches = args.no_trace or _resume_trace_matches(
                    args.trace_dir, q, prior, real_mode=args.real
                )
                if (
                    prior.input_fingerprint == question_fingerprint(q.question)
                    and bool(prior.execution_fingerprint)
                    and prior.execution_fingerprint == expected_execution_fingerprint
                    and trace_matches
                ):
                    stats["skipped_count"] = _int_stat(stats, "skipped_count") + 1
                    continue
                prior_line = prior.model_dump_json(ensure_ascii=False)
                output_lines.remove(prior_line)
                output_bytes -= len((prior_line + "\n").encode("utf-8"))
                skip_ids.remove(q.question_id)
                kept_results.pop(q.question_id)
                stats["kept_existing_count"] = max(
                    0, _int_stat(stats, "kept_existing_count") - 1
                )
            item_started = time.perf_counter()
            result = solve_question(
                q,
                mock=not args.real,
                enable_tools=args.enable_tools,
                save_trace=not args.no_trace,
                trace_dir=args.trace_dir,
                run_mode=args.mode,
            )
        except Exception as exc:
            qid = _failure_question_id(raw, idx)
            question = str(raw.get("question", "")) if isinstance(raw, dict) else ""
            result = make_failure_result(
                question_id=qid,
                question=question,
                error_message=safe_exception_text(exc),
            )
            if not args.no_trace:
                failure_trace_path = trace_path_for_question(
                    args.trace_dir, result.question_id
                )
                if not failure_trace_path.exists():
                    write_trace(
                        {
                            "question_id": result.question_id,
                            "question": question,
                            "model_calls": [],
                            "tool_calls": [],
                            "errors": [safe_exception_text(exc)],
                            "final_result": result.model_dump(),
                        },
                        args.trace_dir,
                        result.question_id,
                    )
            item_started = time.perf_counter()
            stats["error_count"] = _int_stat(stats, "error_count") + 1
        result_line = result.model_dump_json(ensure_ascii=False)
        result_line_bytes = len((result_line + "\n").encode("utf-8"))
        if result_line_bytes > MAX_BATCH_RESULT_LINE_BYTES:
            raise ValueError("batch result row exceeds the size limit")
        output_bytes += result_line_bytes
        if output_bytes > MAX_BATCH_OUTPUT_BYTES:
            raise ValueError("batch output exceeds the byte budget")
        output_lines.append(result_line)
        elapsed = time.perf_counter() - item_started
        stats["processed_count"] = _int_stat(stats, "processed_count") + 1
        stats["total_elapsed_seconds"] = (
            _float_stat(stats, "total_elapsed_seconds") + elapsed
        )
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        if not args.no_trace:
            budget = _read_trace_budget(args.trace_dir, result.question_id)
            stats["total_model_calls"] = (
                _int_stat(stats, "total_model_calls") + budget["model_calls"]
            )
            stats["total_tool_calls"] = (
                _int_stat(stats, "total_tool_calls") + budget["tool_calls"]
            )
            stats["trace_found_count"] = (
                _int_stat(stats, "trace_found_count") + budget["trace_found"]
            )
            trace_bytes += budget["file_bytes"]
            if trace_bytes > MAX_BATCH_TRACE_BYTES:
                raise ValueError("batch traces exceed the byte budget")
            stats["trace_bytes"] = trace_bytes
    atomic_text_write("".join(line + "\n" for line in output_lines), output_path)
    total_elapsed = time.perf_counter() - batch_started
    processed = _int_stat(stats, "processed_count")
    stats["wall_elapsed_seconds"] = total_elapsed
    stats["average_elapsed_seconds"] = (
        _float_stat(stats, "total_elapsed_seconds") / processed if processed else 0.0
    )
    stats["average_model_calls_per_item"] = (
        _int_stat(stats, "total_model_calls") / processed if processed else 0.0
    )
    stats["status_counts"] = dict(sorted(status_counts.items()))
    if stats_path is not None:
        safe_text_write(json.dumps(stats, ensure_ascii=False, indent=2), stats_path)
    print(str(output_path))
    if args.fail_on_non_success:
        if not output_lines:
            return 1
        if any(
            not is_semantically_successful(SolveResult.model_validate_json(line))
            for line in output_lines
        ):
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="math_agent")
    sub = parser.add_subparsers(dest="command", required=True)
    solve_p = sub.add_parser("solve")
    solve_p.add_argument("--question", required=True)
    solve_p.add_argument("--question-id", default="cli_q")
    solve_p.add_argument("--real", action="store_true", default=False)
    solve_p.add_argument("--enable-tools", action="store_true", default=False)
    solve_p.add_argument("--trace-dir", default="outputs/traces")
    solve_p.add_argument("--no-trace", action="store_true", default=False)
    solve_p.add_argument(
        "--fail-on-non-success",
        action="store_true",
        default=False,
        help="Return a non-zero exit code unless the structured result is successful.",
    )
    solve_p.add_argument(
        "--mode", choices=["full", "fast", "tool-first"], default="full"
    )
    solve_p.add_argument("--hard-mode", action="store_true", default=False)
    solve_p.add_argument(
        "--hard-mode-level",
        choices=["off", "light", "standard", "strict"],
        default="standard",
    )
    solve_p.set_defaults(func=cmd_solve)
    batch_p = sub.add_parser("batch")
    batch_p.add_argument("--input", required=True)
    batch_p.add_argument("--output", required=True)
    batch_p.add_argument("--real", action="store_true", default=False)
    batch_p.add_argument("--enable-tools", action="store_true", default=False)
    batch_p.add_argument("--trace-dir", default="outputs/traces")
    batch_p.add_argument("--no-trace", action="store_true", default=False)
    batch_p.add_argument(
        "--fail-on-non-success",
        action="store_true",
        default=False,
        help="Return non-zero if the batch is empty or any result is not successful.",
    )
    batch_p.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Skip question_ids already present in the output file.",
    )
    batch_p.add_argument(
        "--retry-failed",
        action="store_true",
        default=False,
        help="With --resume, keep successful rows and rerun fail/partial rows.",
    )
    batch_p.add_argument(
        "--mode", choices=["full", "fast", "tool-first"], default="full"
    )
    batch_p.add_argument(
        "--stats",
        default=None,
        help="Optional JSON path for batch budget/runtime statistics.",
    )
    batch_p.set_defaults(func=cmd_batch)
    return parser


def main() -> int:
    load_dotenv(override=False)
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
