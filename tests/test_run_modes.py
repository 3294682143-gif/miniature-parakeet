from math_agent.pipeline import MathAgentPipeline
from math_agent.schemas import SolveResult


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.model = "fake-intern-s1"

    def chat(self, messages, **kwargs):
        self.calls += 1
        # planner/verifier need JSON, solver needs boxed answer
        text = str(messages[-1].get("content", ""))
        if "Return JSON with keys" in text:
            return '{"problem_parse":{"goal":"g","givens":[],"symbols":[]},"solution_plan":["s1"]}'
        if "Return JSON with method/passed/notes" in text:
            return '{"method":"self_review","passed":true,"notes":"ok"}'
        return "步骤推导完成。"


def test_full_mode_fake_client_about_three_calls():
    c = FakeClient()
    out = MathAgentPipeline(client=c, mock=False, run_mode="full", enable_tools=False).solve("解方程 2x+5=13", "m1")
    assert isinstance(out, SolveResult)
    assert c.calls == 3


def test_fast_mode_uses_fewer_model_calls_than_full():
    c_full = FakeClient()
    MathAgentPipeline(client=c_full, mock=False, run_mode="full", enable_tools=False).solve("解方程 2x+5=13", "m2")
    c_fast = FakeClient()
    out = MathAgentPipeline(client=c_fast, mock=False, run_mode="fast", enable_tools=False).solve("解方程 2x+5=13", "m3")
    assert isinstance(out, SolveResult)
    assert c_fast.calls < c_full.calls


def test_tool_first_reduces_model_calls_when_tool_success():
    c = FakeClient()
    out = MathAgentPipeline(client=c, mock=False, run_mode="tool-first", enable_tools=True).solve("解方程 2x+5=13", "m4")
    assert isinstance(out, SolveResult)
    assert out.final_answer.value
    assert out.verification.passed is True
    assert c.calls == 0
