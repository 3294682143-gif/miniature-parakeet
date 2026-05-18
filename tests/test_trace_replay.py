import json
import subprocess
import sys
from pathlib import Path

from math_agent.harness.replay import build_timeline, render_replay_markdown, summarize_trace
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


def test_read_trace_missing(tmp_path: Path):
    result = read_trace(tmp_path / "missing.json")
    assert result["ok"] is False
    assert result["error"]["code"] == "file_not_found"


def test_read_trace_bad_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{bad", encoding="utf-8")
    result = read_trace(p)
    assert result["ok"] is False
    assert result["error"]["code"] == "bad_json"


def test_redact_sensitive_fields(tmp_path: Path):
    p = tmp_path / "secret.json"
    payload = {"api_key": "sk-xxx", "headers": {"Authorization": "Bearer aaa"}}
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
    summary = summarize_trace({"question_id": "q", "question": "x", "final_result": {"status": "partial"}})
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
    cmd = [sys.executable, "scripts/replay_trace.py", "--trace-dir", str(d), "--out", str(out_md)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert out.returncode == 0
    assert out_md.exists()
