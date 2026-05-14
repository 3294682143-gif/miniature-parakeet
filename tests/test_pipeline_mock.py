from math_agent.pipeline import MathAgentPipeline, extract_boxed_answer
from math_agent.schemas import SolveResult, Verification


def test_extract_boxed_answer():
    assert extract_boxed_answer("过程... \\boxed{42}") == "42"


def test_pipeline_mock_success_and_schema():
    result = MathAgentPipeline(mock=True).solve("1+1=?", "q1")
    assert isinstance(result, SolveResult)
    assert result.status == "success"


def test_pipeline_calls_all_agents(monkeypatch):
    calls = []

    class DummyRoute:
        domain = "Arithmetic"; problem_type = "calculation"; reason = "ok"; confidence = 0.8

    monkeypatch.setattr("math_agent.pipeline.router.Router.route", lambda self, q: calls.append("route") or DummyRoute())
    monkeypatch.setattr("math_agent.pipeline.planner.Planner.plan", lambda self, q, r: calls.append("plan") or {"k": "v"})
    monkeypatch.setattr("math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: calls.append("solve") or "\\boxed{2}")
    monkeypatch.setattr("math_agent.pipeline.verifier.Verifier.verify", lambda self, q, d, f, r=None: calls.append("verify") or Verification(method="self_review", passed=True, notes="pass"))
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: calls.append("explain") or "hint")
    result = MathAgentPipeline(mock=True).solve("1+1=?", "q2")
    assert result.final_answer.boxed == "\\boxed{2}"
    assert calls == ["route", "plan", "solve", "verify", "explain"]


def test_refiner_called_when_verifier_fails(monkeypatch):
    state = {"verify": 0, "refine": 0}
    class DummyRoute:
        domain="Arithmetic"; problem_type="calculation"; reason="ok"; confidence=0.8
    monkeypatch.setattr("math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute())
    monkeypatch.setattr("math_agent.pipeline.planner.Planner.plan", lambda self, q, r: {"k":"v"})
    monkeypatch.setattr("math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: "answer: 1")
    def fake_verify(self, q, d, f, r=None):
        state["verify"] += 1
        return Verification(method="self_review", passed=state["verify"] > 1, notes="x")
    monkeypatch.setattr("math_agent.pipeline.verifier.Verifier.verify", fake_verify)
    monkeypatch.setattr("math_agent.pipeline.refiner.run", lambda x: state.__setitem__("refine", state["refine"] + 1) or "\\boxed{2}")
    out = MathAgentPipeline(mock=False, max_refine_rounds=1).solve("1+1=?", "q3")
    assert state["refine"] == 1
    assert out.verification.passed is True


def test_non_proof_prefers_boxed_and_not_long_markdown(monkeypatch):
    class DummyRoute:
        domain = "Optimization"; problem_type = "optimization"; recommended_solver = "optimization"; reason = "ok"; confidence = 0.9

    long_draft = "### 问题解析\n很多解释\n最终得到 \\boxed{\\dfrac{1}{4}}"
    monkeypatch.setattr("math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute())
    monkeypatch.setattr("math_agent.pipeline.planner.Planner.plan", lambda self, q, r: {"problem_parse": {}, "solution_plan": []})
    monkeypatch.setattr("math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: long_draft)
    monkeypatch.setattr("math_agent.pipeline.verifier.Verifier.verify", lambda self, q, d, f, r=None: Verification(method="self_review", passed=True, notes="pass"))
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: "hint")

    out = MathAgentPipeline(mock=False).solve("opt", "smoke_005")
    assert out.final_answer.type in {"number", "expression"}
    assert out.final_answer.value in {r"\dfrac{1}{4}", "1/4"}
    assert out.final_answer.boxed in {r"\boxed{\dfrac{1}{4}}", r"\boxed{1/4}"}
    assert len(out.final_answer.boxed) <= 120
    assert "###" not in out.final_answer.boxed
