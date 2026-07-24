import ast
import os
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_demo_module():
    module_path = Path(__file__).resolve().parents[1] / "demo" / "streamlit_app.py"
    spec = spec_from_file_location("streamlit_app", module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeRouter:
    def route(self, question: str):
        return SimpleNamespace(recommended_solver="fake", question=question)


class _FakeDemoPipeline:
    def __init__(self, *, mock: bool, trace_dir: Path, **_kwargs) -> None:
        assert mock is True
        self.trace_dir = Path(trace_dir)
        self.router = _FakeRouter()

    def solve(self, *, question: str, question_id: str):
        (self.trace_dir / f"{question_id}.json").write_bytes(b"new123")
        return SimpleNamespace(question_id=question_id, question=question)


def test_streamlit_demo_module_importable() -> None:
    app = _load_demo_module()
    assert callable(app.main)


def test_run_demo_pipeline_is_mock_only_and_uses_session_trace_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    trace_root = tmp_path / "server-owned-demo-traces"
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", trace_root)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0, raising=False)
    session_id = "a" * 32

    result, trace_path, route_info = app.run_demo_pipeline(
        "Calculate 2+3",
        session_id=session_id,
        enable_tools=True,
        max_refine_rounds=1,
        mode="full",
    )

    expected_dir = (trace_root / session_id).resolve()
    assert trace_path.parent.resolve() == expected_dir
    assert trace_path.exists()
    assert re.fullmatch(r"demo_[0-9a-f]{32}", result.question_id)
    assert trace_path.name == f"{result.question_id}.json"
    assert result.status in {"success", "partial", "fail"}
    assert route_info.recommended_solver

    first_trace = trace_path.read_bytes()
    _, second_trace_path, _ = app.run_demo_pipeline(
        "Calculate 7-4",
        session_id=session_id,
        enable_tools=False,
        max_refine_rounds=1,
        mode="full",
    )
    assert second_trace_path != trace_path
    assert trace_path.read_bytes() == first_trace


def test_session_trace_dir_rejects_untrusted_session_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")

    for session_id in ("../escape", "a/b", "", "A" * 32, "a" * 31):
        with pytest.raises(ValueError, match="session"):
            app._session_trace_dir(session_id)


def test_replay_accepts_only_enumerated_server_trace_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    session_id = "b" * 32
    trace_dir = app._session_trace_dir(session_id)
    trace_dir.mkdir(parents=True)

    allowed_id = "demo_" + "c" * 32
    (trace_dir / f"{allowed_id}.json").write_text("{}", encoding="utf-8")
    (trace_dir / "arbitrary.json").write_text("{}", encoding="utf-8")

    assert app.list_session_trace_ids(session_id) == [allowed_id]
    assert app.read_session_trace(session_id, allowed_id)["ok"] is True
    with pytest.raises(ValueError, match="trace ID"):
        app.read_session_trace(session_id, "../../victim")
    with pytest.raises(ValueError, match="trace ID"):
        app.read_session_trace(session_id, "arbitrary")


def test_trace_retention_enforces_ttl_count_and_total_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_DEMO_TRACE_TTL_SECONDS", 10.0, raising=False)
    monkeypatch.setattr(app, "_DEMO_SESSION_TRACE_LIMIT", 2, raising=False)
    monkeypatch.setattr(app, "_DEMO_SESSION_BYTE_LIMIT", 7, raising=False)
    monkeypatch.setattr(app, "_DEMO_TRACE_BYTE_LIMIT", 7, raising=False)
    monkeypatch.setattr(app, "_TRACE_DIRECTORY_SCAN_LIMIT", 8, raising=False)
    monkeypatch.setattr(app, "_wall_time", lambda: 1_000.0, raising=False)
    session_id = "d" * 32
    trace_dir = app._session_trace_dir(session_id)
    trace_dir.mkdir(parents=True)

    expired_id = "demo_" + "1" * 32
    oldest_id = "demo_" + "2" * 32
    middle_id = "demo_" + "3" * 32
    newest_id = "demo_" + "4" * 32
    fixtures = (
        (expired_id, b"x", 980.0),
        (oldest_id, b"aaaa", 997.0),
        (middle_id, b"bbbb", 998.0),
        (newest_id, b"cccc", 999.0),
    )
    for trace_id, payload, modified_at in fixtures:
        path = trace_dir / f"{trace_id}.json"
        path.write_bytes(payload)
        os.utime(path, (modified_at, modified_at))

    assert app.list_session_trace_ids(session_id) == [newest_id]
    assert not (trace_dir / f"{expired_id}.json").exists()
    assert not (trace_dir / f"{oldest_id}.json").exists()
    assert not (trace_dir / f"{middle_id}.json").exists()
    assert (trace_dir / f"{newest_id}.json").exists()

    count_session_id = "e" * 32
    count_dir = app._session_trace_dir(count_session_id)
    count_dir.mkdir(parents=True)
    count_ids = ["demo_" + digit * 32 for digit in ("5", "6", "7")]
    monkeypatch.setattr(app, "_DEMO_SESSION_BYTE_LIMIT", 100, raising=False)
    for offset, trace_id in enumerate(count_ids):
        path = count_dir / f"{trace_id}.json"
        path.write_bytes(b"ok")
        modified_at = 997.0 + offset
        os.utime(path, (modified_at, modified_at))

    assert app.list_session_trace_ids(count_session_id) == list(reversed(count_ids[1:]))
    assert not (count_dir / f"{count_ids[0]}.json").exists()


def test_trace_enumeration_fails_closed_before_sorting_an_oversized_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_TRACE_DIRECTORY_SCAN_LIMIT", 3, raising=False)
    session_id = "f" * 32
    trace_dir = app._session_trace_dir(session_id)
    trace_dir.mkdir(parents=True)
    for index in range(4):
        (trace_dir / f"entry-{index}.txt").write_text("x", encoding="utf-8")

    with pytest.raises(app.DemoTraceBudgetError, match="too many entries"):
        app.list_session_trace_ids(session_id)


def test_run_demo_pipeline_rate_limits_each_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 60.0, raising=False)
    ticks = iter((100.0, 101.0))
    monkeypatch.setattr(app, "_monotonic", lambda: next(ticks), raising=False)
    session_id = "8" * 32

    app.run_demo_pipeline(
        "Calculate 2+3",
        session_id=session_id,
        enable_tools=False,
        max_refine_rounds=0,
        mode="fast",
    )
    with pytest.raises(app.DemoRateLimitError, match="too quickly"):
        app.run_demo_pipeline(
            "Calculate 7-4",
            session_id=session_id,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )


@pytest.mark.parametrize(
    ("question", "character_limit", "byte_limit", "message"),
    (
        ("123456", 5, 32, "character limit"),
        ("界界界", 8, 8, "UTF-8 byte limit"),
    ),
)
def test_run_demo_pipeline_rejects_oversized_questions_before_allocating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    character_limit: int,
    byte_limit: int,
    message: str,
) -> None:
    app = _load_demo_module()
    trace_root = tmp_path / "traces"
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", trace_root)
    monkeypatch.setattr(app, "_DEMO_QUESTION_CHARACTER_LIMIT", character_limit)
    monkeypatch.setattr(app, "_DEMO_QUESTION_UTF8_BYTE_LIMIT", byte_limit)
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)

    with pytest.raises(app.DemoInputError, match=message):
        app.run_demo_pipeline(
            question,
            session_id="7" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    assert not trace_root.exists()
    assert app._LAST_SOLVE_AT == {}


def test_global_ingress_rate_cannot_be_bypassed_by_rotating_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SOLVE_WINDOW_SECONDS", 60.0)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SOLVE_LIMIT", 2)
    monkeypatch.setattr(app, "_DEMO_NEW_SESSION_LIMIT", 10)
    ticks = iter((100.0, 101.0, 102.0))
    monkeypatch.setattr(app, "_monotonic", lambda: next(ticks))
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)

    for digit in ("1", "2"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id=digit * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    with pytest.raises(app.DemoRateLimitError, match="global solve rate"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id="3" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )


def test_new_session_admission_is_bounded_without_blocking_existing_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SOLVE_LIMIT", 10)
    monkeypatch.setattr(app, "_DEMO_NEW_SESSION_WINDOW_SECONDS", 60.0)
    monkeypatch.setattr(app, "_DEMO_NEW_SESSION_LIMIT", 2)
    monkeypatch.setattr(app, "_ADMITTED_SESSION_TTL_SECONDS", 60.0)
    ticks = iter((100.0, 101.0, 102.0, 103.0))
    monkeypatch.setattr(app, "_monotonic", lambda: next(ticks))
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)

    for digit in ("4", "5"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id=digit * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    with pytest.raises(app.DemoRateLimitError, match="new session rate"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id="6" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    app.run_demo_pipeline(
        "Calculate 7-4",
        session_id="4" * 32,
        enable_tools=False,
        max_refine_rounds=0,
        mode="fast",
    )


def test_active_session_admission_keeps_headroom_below_trace_storage_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    root = tmp_path / "traces"
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", root)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SOLVE_LIMIT", 10)
    monkeypatch.setattr(app, "_DEMO_NEW_SESSION_LIMIT", 10)
    monkeypatch.setattr(app, "_DEMO_ACTIVE_SESSION_LIMIT", 2)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SESSION_LIMIT", 4)
    ticks = iter((100.0, 101.0, 102.0))
    monkeypatch.setattr(app, "_monotonic", lambda: next(ticks))
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)

    for digit in ("7", "8"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id=digit * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    with pytest.raises(app.DemoRateLimitError, match="active session limit"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id="9" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    assert len(list(root.iterdir())) == 2
    assert not (root / ("9" * 32)).exists()


def test_ingress_windows_expire_and_keep_fixed_size_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SOLVE_WINDOW_SECONDS", 10.0)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SOLVE_LIMIT", 2)
    monkeypatch.setattr(app, "_DEMO_NEW_SESSION_WINDOW_SECONDS", 10.0)
    monkeypatch.setattr(app, "_DEMO_NEW_SESSION_LIMIT", 2)
    monkeypatch.setattr(app, "_ADMITTED_SESSION_TTL_SECONDS", 10.0)
    ticks = iter((100.0, 101.0, 112.0))
    monkeypatch.setattr(app, "_monotonic", lambda: next(ticks))
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)

    for digit in ("a", "b", "c"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id=digit * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    assert len(app._GLOBAL_SOLVE_TIMES) <= app._DEMO_GLOBAL_SOLVE_LIMIT
    assert len(app._NEW_SESSION_TIMES) <= app._DEMO_NEW_SESSION_LIMIT
    assert len(app._ADMITTED_SESSION_AT) <= app._DEMO_NEW_SESSION_LIMIT


def test_run_demo_pipeline_prunes_oldest_trace_at_count_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_DEMO_SESSION_TRACE_LIMIT", 1, raising=False)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0, raising=False)
    session_id = "9" * 32

    _, first_trace_path, _ = app.run_demo_pipeline(
        "Calculate 2+3",
        session_id=session_id,
        enable_tools=False,
        max_refine_rounds=0,
        mode="fast",
    )
    second_result, second_trace_path, _ = app.run_demo_pipeline(
        "Calculate 7-4",
        session_id=session_id,
        enable_tools=False,
        max_refine_rounds=0,
        mode="fast",
    )

    assert second_trace_path.exists()
    assert not first_trace_path.exists()
    assert app.list_session_trace_ids(session_id) == [second_result.question_id]


def test_run_demo_pipeline_removes_a_new_trace_that_exceeds_byte_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", tmp_path / "traces")
    monkeypatch.setattr(app, "_DEMO_SESSION_BYTE_LIMIT", 64, raising=False)
    monkeypatch.setattr(app, "_DEMO_TRACE_BYTE_LIMIT", 32, raising=False)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0, raising=False)
    session_id = "0" * 32

    with pytest.raises(app.DemoTraceBudgetError, match="byte limit"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id=session_id,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )

    trace_dir = app._session_trace_dir(session_id)
    assert list(trace_dir.glob("*.json")) == []


def test_global_session_limit_cannot_be_bypassed_with_new_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    root = tmp_path / "traces"
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", root)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SESSION_LIMIT", 2, raising=False)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)
    for digit in ("a", "b"):
        session_id = digit * 32
        trace_dir = app._session_trace_dir(session_id)
        trace_dir.mkdir(parents=True)
        (trace_dir / f"demo_{digit * 32}.json").write_bytes(b"active")

    with pytest.raises(app.DemoTraceBudgetError, match="global session limit"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id="c" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )
    assert not (root / ("c" * 32)).exists()


def test_global_trace_file_and_byte_limits_reject_new_solves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    root = tmp_path / "traces"
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", root)
    monkeypatch.setattr(app, "_DEMO_TRACE_BYTE_LIMIT", 8)
    monkeypatch.setattr(app, "_DEMO_SESSION_BYTE_LIMIT", 32)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_BYTE_LIMIT", 10, raising=False)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_TRACE_LIMIT", 10, raising=False)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)
    existing_session = "d" * 32
    existing_dir = app._session_trace_dir(existing_session)
    existing_dir.mkdir(parents=True)
    existing_trace = existing_dir / f"demo_{'d' * 32}.json"
    existing_trace.write_bytes(b"active")

    with pytest.raises(app.DemoTraceBudgetError, match="global byte limit"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id="e" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )
    assert existing_trace.exists()

    monkeypatch.setattr(app, "_DEMO_GLOBAL_BYTE_LIMIT", 64, raising=False)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_TRACE_LIMIT", 1, raising=False)
    with pytest.raises(app.DemoTraceBudgetError, match="global trace limit"):
        app.run_demo_pipeline(
            "Calculate 7-4",
            session_id="f" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )
    assert existing_trace.exists()


def test_new_solve_cleans_expired_traces_from_abandoned_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    root = tmp_path / "traces"
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", root)
    monkeypatch.setattr(app, "_DEMO_GLOBAL_SESSION_LIMIT", 1, raising=False)
    monkeypatch.setattr(app, "_DEMO_TRACE_TTL_SECONDS", 10.0)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "_wall_time", lambda: 1_000.0)
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)
    abandoned_session = "1" * 32
    abandoned_dir = app._session_trace_dir(abandoned_session)
    abandoned_dir.mkdir(parents=True)
    expired_trace = abandoned_dir / f"demo_{'1' * 32}.json"
    expired_trace.write_bytes(b"expired")
    os.utime(expired_trace, (980.0, 980.0))

    result, trace_path, _ = app.run_demo_pipeline(
        "Calculate 2+3",
        session_id="2" * 32,
        enable_tools=False,
        max_refine_rounds=0,
        mode="fast",
    )

    assert result.question_id == trace_path.stem
    assert trace_path.exists()
    assert not abandoned_dir.exists()


def test_trace_root_enumeration_has_a_hard_entry_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    root = tmp_path / "traces"
    root.mkdir()
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", root)
    monkeypatch.setattr(app, "_TRACE_ROOT_SCAN_LIMIT", 3, raising=False)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)
    for index in range(4):
        (root / f"unexpected-{index}").mkdir()

    with pytest.raises(app.DemoTraceBudgetError, match="root has too many entries"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id="3" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )


def test_trace_root_does_not_follow_session_directory_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _load_demo_module()
    root = tmp_path / "traces"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    linked_session = root / ("4" * 32)
    try:
        linked_session.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    monkeypatch.setattr(app, "DEMO_TRACE_ROOT", root)
    monkeypatch.setattr(app, "_DEMO_MIN_SOLVE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(app, "MathAgentPipeline", _FakeDemoPipeline)

    with pytest.raises(app.DemoTraceBudgetError, match="symbolic link"):
        app.run_demo_pipeline(
            "Calculate 2+3",
            session_id="5" * 32,
            enable_tools=False,
            max_refine_rounds=0,
            mode="fast",
        )
    assert list(outside.iterdir()) == []


def test_streamlit_source_has_no_runtime_or_path_input_controls() -> None:
    module_path = Path(__file__).resolve().parents[1] / "demo" / "streamlit_app.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    text_input_labels: set[str] = set()
    real_mode_selectors = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "text_input" and node.args:
            label = node.args[0]
            if isinstance(label, ast.Constant) and isinstance(label.value, str):
                text_input_labels.add(label.value)
        if node.func.attr == "selectbox" and len(node.args) >= 2:
            options = node.args[1]
            if isinstance(options, (ast.List, ast.Tuple)) and any(
                isinstance(item, ast.Constant) and item.value == "real"
                for item in options.elts
            ):
                real_mode_selectors += 1

    assert "trace_dir" not in text_input_labels
    assert "trace file path" not in text_input_labels
    assert "question_id" not in text_input_labels
    assert real_mode_selectors == 0
