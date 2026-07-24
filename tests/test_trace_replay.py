# safety: allow-secret-fixtures
import json
import subprocess
import sys
from pathlib import Path

from math_agent.harness.replay import (
    build_timeline,
    render_replay_markdown,
    summarize_trace,
)
from math_agent.harness.trace_reader import read_trace, read_trace_dir


def _sample_trace() -> dict:
    return {
        "question_id": "q1",
        "question": "1+1=?",
        "latency_seconds": 0.12,
        "route_info": {"domain": "calculation", "problem_type": "calculation"},
        "model_calls": [{"stage": "planner"}, {"stage": "solver"}],
        "tool_calls": [{"tool": "python"}],
        "final_result": {
            "status": "success",
            "confidence": 0.9,
            "final_answer": {"value": "2"},
            "verification": {"passed": True, "method": "numeric_check"},
        },
    }


def test_read_trace_ok(tmp_path: Path):
    p = tmp_path / "q1.json"
    p.write_text(json.dumps(_sample_trace()), encoding="utf-8")
    result = read_trace(p)
    assert result["ok"] is True
    assert result["trace"]["question_id"] == "q1"


def test_read_trace_returns_verified_bytes_without_exposing_hash_path(
    tmp_path: Path,
) -> None:
    digest = "0123456789abcdef" * 4
    path = tmp_path / f"~trace-{digest}.json"
    path.write_text(json.dumps(_sample_trace()), encoding="utf-8")

    result = read_trace(path)

    assert result["ok"] is True
    assert result["path"] == "[redacted-path]"
    assert result["file_bytes"] == len(path.read_bytes())


def test_untrusted_trace_reader_does_not_preserve_hash_shaped_fields(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789abcdef" * 4
    path = tmp_path / "untrusted.json"
    path.write_text(
        json.dumps(
            {
                "input_fingerprint": fingerprint,
                "execution_profile": {"prompt_config_sha256": fingerprint},
                "final_result": {"execution_fingerprint": fingerprint},
            }
        ),
        encoding="utf-8",
    )

    result = read_trace(path)

    assert result["trace"]["input_fingerprint"] == "[REDACTED]"
    assert result["trace"]["execution_profile"]["prompt_config_sha256"] == (
        "[REDACTED]"
    )
    assert result["trace"]["final_result"]["execution_fingerprint"] == "[REDACTED]"


def test_trusted_program_trace_reader_preserves_only_exact_hash_paths(
    tmp_path: Path,
) -> None:
    import math_agent.harness.trace_reader as reader

    fingerprint = "0123456789abcdef" * 4
    path = tmp_path / "program-trace.json"
    path.write_text(
        json.dumps(
            {
                "input_fingerprint": fingerprint,
                "execution_fingerprint": fingerprint,
                "execution_profile": {
                    "prompt_config_sha256": fingerprint,
                    "metadata": {"input_fingerprint": fingerprint},
                },
                "final_result": {
                    "input_fingerprint": fingerprint,
                    "execution_fingerprint": fingerprint,
                    "metadata": {"sha256": fingerprint},
                },
                "metadata": {"input_fingerprint": fingerprint},
            }
        ),
        encoding="utf-8",
    )

    result = reader.read_trusted_program_trace(path)

    assert result["trace"]["input_fingerprint"] == fingerprint
    assert result["trace"]["execution_fingerprint"] == fingerprint
    assert result["trace"]["execution_profile"]["prompt_config_sha256"] == fingerprint
    assert result["trace"]["final_result"]["input_fingerprint"] == fingerprint
    assert result["trace"]["final_result"]["execution_fingerprint"] == fingerprint
    assert result["trace"]["execution_profile"]["metadata"] == {
        "input_fingerprint": "[REDACTED]"
    }
    assert result["trace"]["final_result"]["metadata"] == {"sha256": "[REDACTED]"}
    assert result["trace"]["metadata"] == {"input_fingerprint": "[REDACTED]"}


def test_read_trace_missing(tmp_path: Path):
    result = read_trace(tmp_path / "missing.json")
    assert result["ok"] is False
    assert result["error"]["code"] == "file_not_found"


def test_trace_reader_never_echoes_secret_shaped_paths(tmp_path: Path):
    secret = "xapp-1-ABCDEFGHIJKLMNOP-1234567890-abcdefghijklmnopqrstuv"
    result = read_trace(tmp_path / f"{secret}.json")

    rendered = json.dumps(result)
    assert secret not in rendered
    assert "[redacted-path]" in rendered


def test_read_trace_bad_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{bad", encoding="utf-8")
    result = read_trace(p)
    assert result["ok"] is False
    assert result["error"]["code"] == "bad_json"
    assert result["file_bytes"] == len(p.read_bytes())


def test_read_trace_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    p = tmp_path / "duplicate.json"
    p.write_text(
        '{"question_id":"q1","final_result":{"status":"fail","status":"success"}}',
        encoding="utf-8",
    )

    result = read_trace(p)

    assert result["ok"] is False
    assert result["error"]["code"] == "bad_json"


def test_read_trace_rejects_non_object_json(tmp_path: Path):
    p = tmp_path / "scalar.json"
    p.write_text('"value"', encoding="utf-8")

    result = read_trace(p)

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_trace_root"


def test_read_trace_enforces_size_limit(tmp_path: Path, monkeypatch):
    import math_agent.harness.trace_reader as reader

    p = tmp_path / "large.json"
    p.write_text('{"padding":"1234567890"}', encoding="utf-8")
    monkeypatch.setattr(reader, "MAX_TRACE_FILE_BYTES", 8)

    result = reader.read_trace(p)

    assert result["ok"] is False
    assert result["error"]["code"] == "trace_too_large"


def test_read_trace_rejects_file_growth_during_bounded_read(
    tmp_path: Path, monkeypatch
) -> None:
    import math_agent.harness.trace_reader as reader

    path = tmp_path / "growing.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(reader, "MAX_TRACE_FILE_BYTES", 64)
    original_read = reader.os.read
    appended = False

    def grow_then_read(descriptor: int, size: int) -> bytes:
        nonlocal appended
        if not appended:
            appended = True
            with path.open("ab") as handle:
                handle.write(b" " * 65)
        return original_read(descriptor, size)

    monkeypatch.setattr(reader.os, "read", grow_then_read)

    result = reader.read_trace(path)

    assert result["ok"] is False
    assert result["error"]["code"] == "trace_too_large"


def test_read_trace_dir_enforces_file_count_limit(tmp_path: Path, monkeypatch):
    import math_agent.harness.trace_reader as reader

    for index in range(3):
        (tmp_path / f"{index}.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(reader, "MAX_TRACE_FILES", 2)

    result = reader.read_trace_dir(tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "too_many_trace_files"


def test_read_trace_dir_stops_enumerating_at_json_candidate_limit(
    monkeypatch,
) -> None:
    import math_agent.harness.trace_reader as reader

    consumed = 0

    class Candidate:
        def __init__(self, index: int) -> None:
            self.name = f"{index}.json"

        def __lt__(self, other) -> bool:
            return self.name < other.name

    class Root:
        def __str__(self) -> str:
            return "fake-traces"

        def is_symlink(self) -> bool:
            return False

        def is_junction(self) -> bool:
            return False

        def exists(self) -> bool:
            return True

        def is_dir(self) -> bool:
            return True

        def iterdir(self):
            nonlocal consumed
            for index in range(100):
                consumed += 1
                yield Candidate(index)

    root = Root()
    monkeypatch.setattr(reader, "Path", lambda _path: root)
    monkeypatch.setattr(reader, "MAX_TRACE_FILES", 2)
    monkeypatch.setattr(
        reader, "path_has_link_component", lambda _path: False, raising=False
    )

    result = reader.read_trace_dir("unused")

    assert result["ok"] is False
    assert result["error"]["code"] == "too_many_trace_files"
    assert consumed == 3


def test_read_trace_dir_limits_total_entries_before_materializing(monkeypatch) -> None:
    import math_agent.harness.trace_reader as reader

    consumed = 0

    class Candidate:
        name = "not-a-trace.txt"

    class Root:
        def __str__(self) -> str:
            return "fake-traces"

        def is_symlink(self) -> bool:
            return False

        def is_junction(self) -> bool:
            return False

        def exists(self) -> bool:
            return True

        def is_dir(self) -> bool:
            return True

        def iterdir(self):
            nonlocal consumed
            for _ in range(100):
                consumed += 1
                yield Candidate()

    root = Root()
    monkeypatch.setattr(reader, "Path", lambda _path: root)
    monkeypatch.setattr(reader, "MAX_TRACE_DIR_ENTRIES", 3, raising=False)
    monkeypatch.setattr(
        reader, "path_has_link_component", lambda _path: False, raising=False
    )

    result = reader.read_trace_dir("unused")

    assert result["ok"] is False
    assert result["error"]["code"] == "too_many_trace_entries"
    assert consumed == 4


def test_read_trace_dir_enforces_budget_from_verified_file_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    import math_agent.harness.trace_reader as reader

    for name in ("a.json", "b.json", "c.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    read_paths: list[Path] = []

    def verified_read(path: Path) -> dict:
        read_paths.append(path)
        return {
            "ok": False,
            "path": "[redacted-path]",
            "file_bytes": 2,
            "error": {"code": "bad_json", "message": "invalid trace json"},
            "trace": None,
        }

    class UntrustedMetadata:
        st_size = 0

    monkeypatch.setattr(reader, "MAX_TRACE_DIR_BYTES", 3)
    monkeypatch.setattr(reader, "read_trace", verified_read)
    monkeypatch.setattr(reader.os, "lstat", lambda _path: UntrustedMetadata())

    result = reader.read_trace_dir(tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "trace_directory_too_large"
    assert len(read_paths) == 2


def test_read_trace_rejects_non_finite_numbers(tmp_path: Path) -> None:
    path = tmp_path / "non-finite.json"
    path.write_text('{"latency_seconds": Infinity}', encoding="utf-8")

    result = read_trace(path)

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_trace_value"

    path.write_text("NaN", encoding="utf-8")
    scalar_result = read_trace(path)
    assert scalar_result["ok"] is False
    assert scalar_result["error"]["code"] == "invalid_trace_value"


def test_trace_reader_rejects_unsafe_ancestor(tmp_path: Path, monkeypatch) -> None:
    import math_agent.harness.trace_reader as reader

    path = tmp_path / "trace.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        reader, "path_has_link_component", lambda _path: True, raising=False
    )

    result = reader.read_trace(path)

    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported_trace_file"


def test_redact_sensitive_fields(tmp_path: Path):
    p = tmp_path / "secret.json"
    payload = {"api_key": "mock", "headers": {"Authorization": "Bearer aaa"}}
    p.write_text(json.dumps(payload), encoding="utf-8")
    result = read_trace(p)
    assert result["trace"]["api_key"] == "[REDACTED]"
    assert result["trace"]["headers"]["Authorization"] == "[REDACTED]"


def test_read_trace_dir_multi(tmp_path: Path):
    (tmp_path / "a.json").write_text(json.dumps(_sample_trace()), encoding="utf-8")
    (tmp_path / "b.json").write_text("{bad", encoding="utf-8")
    result = read_trace_dir(tmp_path)
    assert result["ok"] is True
    assert result["total"] == 2
    assert result["ok_count"] == 1


def test_timeline_missing_fields():
    timeline = build_timeline({"question_id": "x"})
    assert any(x["status"] in {"skipped", "unavailable"} for x in timeline)


def test_summarize_missing_final_answer():
    summary = summarize_trace(
        {"question_id": "q", "question": "x", "final_result": {"status": "partial"}}
    )
    assert summary["final_answer"] == ""


def test_markdown_generation():
    md = render_replay_markdown(_sample_trace())
    assert "# Trace Replay" in md
    assert "## Timeline" in md


def test_script_trace(tmp_path: Path):
    p = tmp_path / "q1.json"
    p.write_text(json.dumps(_sample_trace()), encoding="utf-8")
    cmd = [sys.executable, "scripts/replay_trace.py", "--trace", str(p)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert out.returncode == 0
    assert "Trace Replay" in out.stdout


def test_script_trace_dir_out(tmp_path: Path):
    d = tmp_path / "traces"
    d.mkdir()
    (d / "q1.json").write_text(json.dumps(_sample_trace()), encoding="utf-8")
    out_md = tmp_path / "replay.md"
    cmd = [
        sys.executable,
        "scripts/replay_trace.py",
        "--trace-dir",
        str(d),
        "--out",
        str(out_md),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert out.returncode == 0
    assert out_md.exists()
