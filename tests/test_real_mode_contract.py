import json
from math_agent.pipeline import MathAgentPipeline


def test_pipeline_real_uses_client_and_trace_model_calls(tmp_path):
    class FakeClient:
        model = "intern-s1"
        def __init__(self): self.calls = 0
        def chat(self, messages, **kwargs):
            self.calls += 1
            return "这是证明文本，不是42。"
    c = FakeClient()
    p = MathAgentPipeline(client=c, mock=False, trace_dir=tmp_path)
    out = p.solve("证明任意偶数的平方仍然是偶数", "q1")
    assert c.calls >= 2
    assert out.final_answer.boxed != "\\boxed{42}"
    trace = json.loads((tmp_path / "q1.json").read_text(encoding="utf-8"))
    assert trace.get("model_calls")
    assert trace.get("model_calls_count", 0) > 0


def test_batch_does_not_interrupt_on_single_failure(tmp_path):
    inp = tmp_path / "in.jsonl"
    inp.write_text('{"question_id":"ok","question":"1+1=?"}\n{"question_id":"bad"}\n', encoding="utf-8")
    outp = tmp_path / "out.jsonl"
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "math_agent.cli", "batch", "--input", str(inp), "--output", str(outp)], check=True)
    assert len(outp.read_text(encoding="utf-8").strip().splitlines()) == 2
