import json
import subprocess
import sys

from math_agent.pipeline import MathAgentPipeline
from math_agent.schemas import MathQuestion, SolveResult


def test_real_missing_key_errors(monkeypatch):
    monkeypatch.delenv("INTERNS1_API_KEY", raising=False)
    monkeypatch.delenv("INTERNS1_BASE_URL", raising=False)
    cmd = [sys.executable, "-m", "math_agent.cli", "solve", "--question", "计算 1+1", "--real"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "missing_api_key" in proc.stderr or "missing_api_key" in proc.stdout


def test_smoke_classify_error():
    from runpy import run_path
    ns = run_path("scripts/smoke_interns1.py")
    classify_error = ns["classify_error"]
    assert classify_error(Exception("missing_api_key: x")) == "missing_api_key"
    assert classify_error(Exception("rate_limit: x")) == "rate_limit"


def test_pipeline_real_like_with_fake_client_success(tmp_path):
    class FakeClient:
        def chat(self, messages, **kwargs):
            return "答案是 \\boxed{2}"

    p = MathAgentPipeline(client=FakeClient(), mock=False, trace_dir=tmp_path)
    out = p.solve("计算 1+1", "q1")
    SolveResult.model_validate(out.model_dump())
    assert out.status in {"success", "partial"}


def test_pipeline_real_like_with_forced_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("math_agent.pipeline.solver.run", lambda q: (_ for _ in ()).throw(RuntimeError("boom")))
    p = MathAgentPipeline(mock=False, trace_dir=tmp_path)
    out = p.solve("计算 1+1", "q2")
    SolveResult.model_validate(out.model_dump())
    assert out.status in {"fail", "partial"}


def test_batch_does_not_interrupt_on_single_failure(tmp_path):
    inp = tmp_path / "in.jsonl"
    inp.write_text('{"question_id":"ok","question":"1+1=?"}\n{"question_id":"bad"}\n', encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    cmd = [sys.executable, "-m", "math_agent.cli", "batch", "--input", str(inp), "--output", str(outp)]
    subprocess.run(cmd, check=True)
    lines = outp.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        SolveResult.model_validate(json.loads(line))


def test_trace_has_no_secrets(tmp_path):
    p = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    _ = p.solve("计算 1+1", "qtrace")
    trace_text = (tmp_path / "qtrace.json").read_text(encoding="utf-8")
    assert "INTERNS1_API_KEY" not in trace_text
    assert "Authorization" not in trace_text
    assert "Bearer" not in trace_text
