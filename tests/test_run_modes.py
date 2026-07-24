from pathlib import Path

from math_agent.io_utils import strict_json_loads
from math_agent.pipeline import MathAgentPipeline
from math_agent.schemas import SolveResult, is_valid_trace_audit_evidence


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


class RefinementClient:
    model = "fake-intern-s1"

    def __init__(self) -> None:
        self.calls = 0
        self.verifier_calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        text = str(messages[-1].get("content", ""))
        if "Return JSON with keys" in text:
            return (
                '{"problem_parse":{"goal":"g","givens":[],"symbols":[]},'
                '"solution_plan":["solve"]}'
            )
        if "Return JSON with method/passed/notes" in text:
            self.verifier_calls += 1
            passed = "true" if self.verifier_calls > 1 else "false"
            return '{"method":"self_review","passed":' + passed + ',"notes":"checked"}'
        if "Please refine the solution" in text:
            return r"Refined derivation. Final answer: \boxed{4}"
        return r"Initial derivation. Final answer: \boxed{5}"


def test_full_mode_fake_client_about_three_calls():
    c = FakeClient()
    out = MathAgentPipeline(
        client=c, mock=False, run_mode="full", enable_tools=False
    ).solve("解方程 2x+5=13", "m1")
    assert isinstance(out, SolveResult)
    assert c.calls == 3


def test_fast_mode_uses_fewer_model_calls_than_full():
    c_full = FakeClient()
    MathAgentPipeline(
        client=c_full, mock=False, run_mode="full", enable_tools=False
    ).solve("解方程 2x+5=13", "m2")
    c_fast = FakeClient()
    out = MathAgentPipeline(
        client=c_fast, mock=False, run_mode="fast", enable_tools=False
    ).solve("解方程 2x+5=13", "m3")
    assert isinstance(out, SolveResult)
    assert (
        c_fast.calls <= c_full.calls
    )  # fast mode skips planner, uses same or fewer calls


def test_tool_first_reduces_model_calls_when_tool_success():
    c = FakeClient()
    out = MathAgentPipeline(
        client=c, mock=False, run_mode="tool-first", enable_tools=True
    ).solve("解方程 2x+5=13", "m4")
    assert isinstance(out, SolveResult)
    assert out.final_answer.value
    assert out.verification.passed is True
    assert c.calls == 1


class AuditedClient(FakeClient):
    def chat(self, messages, **kwargs):
        self.calls += 1
        text = str(messages[-1].get("content", ""))
        if "Return JSON with keys" in text:
            return (
                '{"problem_parse":{"goal":"g","givens":[],"symbols":[]},'
                '"solution_plan":["solve"]}'
            )
        if "Return JSON with method/passed/notes" in text:
            return '{"method":"self_review","passed":true,"notes":"ok"}'
        return r"Derivation. Final answer: \boxed{4}"


def _read_trace(path: Path, question_id: str) -> dict:
    value = strict_json_loads(
        (path / f"{question_id}.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def test_trace_counts_only_actual_calls_in_all_run_modes(tmp_path: Path) -> None:
    cases = [
        ("full", False, 3),
        ("fast", False, 2),
        ("tool-first", True, 1),
    ]
    for mode, enable_tools, expected_calls in cases:
        client = AuditedClient()
        trace_dir = tmp_path / mode
        result = MathAgentPipeline(
            client=client,
            mock=False,
            run_mode=mode,
            enable_tools=enable_tools,
            trace_dir=trace_dir,
        ).solve("Solve 2x+5=13", mode)
        trace = _read_trace(trace_dir, mode)

        assert client.calls == expected_calls
        assert len(trace["model_calls"]) == expected_calls
        assert trace["model_calls_count"] == expected_calls
        assert trace["verifier_result"] == result.verification.model_dump()
        assert is_valid_trace_audit_evidence(trace, result, expected_real_mode=True)
        markerless_trace = {**trace, "metadata": {}}
        assert not is_valid_trace_audit_evidence(
            markerless_trace, result, expected_real_mode=None
        )


def test_mock_trace_does_not_invent_model_calls(tmp_path: Path) -> None:
    client = FakeClient()
    result = MathAgentPipeline(
        client=client, mock=True, run_mode="fast", trace_dir=tmp_path
    ).solve("2+3", "mock-call-count")
    trace = _read_trace(tmp_path, "mock-call-count")

    assert result.status == "success"
    assert client.calls == 0
    assert trace["model_calls"] == []
    assert trace["model_calls_count"] == 0
    assert trace["verifier_result"] == result.verification.model_dump()
    assert is_valid_trace_audit_evidence(trace, result, expected_real_mode=False)


def test_refinement_trace_counts_refiner_and_second_verifier(tmp_path: Path) -> None:
    client = RefinementClient()
    result = MathAgentPipeline(
        client=client,
        mock=False,
        run_mode="full",
        max_refine_rounds=1,
        trace_dir=tmp_path,
    ).solve("What is 2+2?", "refinement")
    trace = _read_trace(tmp_path, "refinement")

    assert client.calls == 5
    assert [call["stage"] for call in trace["model_calls"]] == [
        "planner",
        "solver",
        "verifier",
        "refiner",
        "verifier",
    ]
    assert trace["model_calls_count"] == client.calls
    assert trace["verifier_result"] == result.verification.model_dump()
    assert is_valid_trace_audit_evidence(trace, result, expected_real_mode=True)
