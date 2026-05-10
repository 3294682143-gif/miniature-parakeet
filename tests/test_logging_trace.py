import json
from pathlib import Path

from math_agent.pipeline import MathAgentPipeline
from math_agent.schemas import SolveResult


def test_solve_default_generates_trace(tmp_path: Path):
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    result = pipeline.solve("1+1=?", "q1")
    assert isinstance(result, SolveResult)
    trace_file = tmp_path / "q1.json"
    assert trace_file.exists()
    data = json.loads(trace_file.read_text(encoding="utf-8"))
    assert data["question_id"] == "q1"
    assert data["question"] == "1+1=?"
    assert isinstance(data["final_result"], dict)


def test_no_trace_disable(tmp_path: Path):
    pipeline = MathAgentPipeline(mock=True, save_trace=False, trace_dir=tmp_path)
    pipeline.solve("1+1=?", "q2")
    assert not (tmp_path / "q2.json").exists()


def test_trace_redacts_sensitive_values(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("math_agent.pipeline.planner.run", lambda q: "Authorization: Bearer abc INTERNS1_API_KEY=secret .env")
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    pipeline.solve("1+1=?", "q3")
    content = (tmp_path / "q3.json").read_text(encoding="utf-8")
    assert "INTERNS1_API_KEY" not in content
    assert "Bearer" not in content
    assert "Authorization" not in content


def test_batch_like_multiple_questions_generate_multiple_traces(tmp_path: Path):
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    pipeline.solve("1+1=?", "a")
    pipeline.solve("2+2=?", "b")
    assert (tmp_path / "a.json").exists()
    assert (tmp_path / "b.json").exists()


def test_failure_still_generates_trace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("math_agent.pipeline.planner.run", lambda q: (_ for _ in ()).throw(RuntimeError("fail")))
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    result = pipeline.solve("1+1=?", "qf")
    assert result.status == "fail"
    data = json.loads((tmp_path / "qf.json").read_text(encoding="utf-8"))
    assert data["final_result"]["status"] == "fail"


def test_trace_write_failure_does_not_break_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("math_agent.pipeline.write_trace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    result = pipeline.solve("1+1=?", "qw")
    assert result.status in {"success", "partial"}
