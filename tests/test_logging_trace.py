import json
from pathlib import Path

from math_agent.pipeline import MathAgentPipeline
from math_agent.schemas import SolveResult


def test_solve_generates_trace_by_default(tmp_path: Path):
    result = MathAgentPipeline(mock=True, trace_dir=tmp_path).solve("1+1=?", "q_default")
    assert isinstance(result, SolveResult)
    trace_path = tmp_path / "q_default.json"
    assert trace_path.exists()
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["question_id"] == "q_default"
    assert payload["question"] == "1+1=?"
    assert "final_result" in payload


def test_solve_no_trace(tmp_path: Path):
    MathAgentPipeline(mock=True, save_trace=False, trace_dir=tmp_path).solve("1+1=?", "q_notrace")
    assert not (tmp_path / "q_notrace.json").exists()


def test_trace_hides_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("math_agent.pipeline.verifier.run", lambda q: "INTERNS1_API_KEY=abc123")
    MathAgentPipeline(mock=False, trace_dir=tmp_path).solve("1+1=?", "q_secret")
    content = (tmp_path / "q_secret.json").read_text(encoding="utf-8")
    assert "INTERNS1_API_KEY" not in content


def test_failure_still_writes_trace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("math_agent.pipeline.planner.run", lambda q: (_ for _ in ()).throw(RuntimeError("boom")))
    result = MathAgentPipeline(mock=True, trace_dir=tmp_path).solve("1+1=?", "q_fail")
    assert result.status == "fail"
    payload = json.loads((tmp_path / "q_fail.json").read_text(encoding="utf-8"))
    assert payload["final_result"]["status"] == "fail"


def test_trace_write_failure_does_not_break(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("math_agent.logging_utils.safe_json_dump", lambda data, path: (_ for _ in ()).throw(OSError("disk full")))
    result = MathAgentPipeline(mock=True, trace_dir=tmp_path).solve("1+1=?", "q_disk")
    assert result.status in {"success", "partial"}
