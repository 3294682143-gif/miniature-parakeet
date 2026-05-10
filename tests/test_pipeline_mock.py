from math_agent.pipeline import MathAgentPipeline, extract_boxed_answer
from math_agent.schemas import SolveResult


def test_extract_boxed_answer():
    assert extract_boxed_answer("过程... \\boxed{42}") == "42"


def test_pipeline_mock_success_and_schema():
    result = MathAgentPipeline(mock=True).solve("1+1=?", "q1")
    assert isinstance(result, SolveResult)
    assert result.status == "success"
    assert result.verification.passed is True
    assert result.final_answer.boxed != ""
    assert 0 <= result.confidence <= 1


def test_pipeline_calls_all_agents(monkeypatch):
    calls = []

    class DummyRoute:
        domain = "Arithmetic"
        problem_type = "calculation"
        reason = "ok"
        confidence = 0.8

    monkeypatch.setattr("math_agent.pipeline.router.Router.route", lambda self, q: calls.append("route") or DummyRoute())
    monkeypatch.setattr("math_agent.pipeline.planner.run", lambda q: calls.append("plan") or "plan")
    monkeypatch.setattr("math_agent.pipeline.solver.run", lambda q: calls.append("solve") or "\\boxed{2}")
    monkeypatch.setattr("math_agent.pipeline.verifier.run", lambda q: calls.append("verify") or "pass")
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: calls.append("explain") or "hint")

    result = MathAgentPipeline(mock=True).solve("1+1=?", "q2")
    assert result.final_answer.boxed == "\\boxed{2}"
    assert calls == ["route", "plan", "solve", "verify", "explain"]


def test_refiner_called_when_verifier_fails(monkeypatch):
    state = {"verify": 0}

    class DummyRoute:
        domain = "Arithmetic"
        problem_type = "calculation"
        reason = "ok"
        confidence = 0.8

    monkeypatch.setattr("math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute())
    monkeypatch.setattr("math_agent.pipeline.planner.run", lambda q: "plan")
    monkeypatch.setattr("math_agent.pipeline.solver.run", lambda q: "answer: 1")

    def fake_verify(q):
        state["verify"] += 1
        return "fail" if state["verify"] == 1 else "pass"

    called = {"refine": 0}
    monkeypatch.setattr("math_agent.pipeline.verifier.run", fake_verify)
    monkeypatch.setattr("math_agent.pipeline.refiner.run", lambda x: called.__setitem__("refine", called["refine"] + 1) or "\\boxed{2}")
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: "hint")

    result = MathAgentPipeline(mock=False, max_refine_rounds=1).solve("1+1=?", "q3")
    assert called["refine"] == 1
    assert result.verification.passed is True


def test_no_refiner_when_rounds_zero(monkeypatch):
    class DummyRoute:
        domain = "Arithmetic"
        problem_type = "calculation"
        reason = "ok"
        confidence = 0.8

    monkeypatch.setattr("math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute())
    monkeypatch.setattr("math_agent.pipeline.planner.run", lambda q: "plan")
    monkeypatch.setattr("math_agent.pipeline.solver.run", lambda q: "answer: 1")
    monkeypatch.setattr("math_agent.pipeline.verifier.run", lambda q: "fail")
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: "hint")

    called = {"refine": 0}
    monkeypatch.setattr("math_agent.pipeline.refiner.run", lambda x: called.__setitem__("refine", called["refine"] + 1) or x)

    result = MathAgentPipeline(mock=False, max_refine_rounds=0).solve("1+1=?", "q4")
    assert called["refine"] == 0
    assert result.status == "partial"


def test_agent_exception_returns_fail(monkeypatch):
    monkeypatch.setattr("math_agent.pipeline.planner.run", lambda q: (_ for _ in ()).throw(RuntimeError("boom")))
    result = MathAgentPipeline(mock=True).solve("1+1=?", "q5")
    assert result.status == "fail"


def test_enable_tools_mock_does_not_call_interns1_api(monkeypatch):
    monkeypatch.setattr("math_agent.clients.interns1_client.InternS1Client.chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("chat should not be called")))
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("计算 2+3", "q_tools")
    assert result.final_answer.value == "5"
