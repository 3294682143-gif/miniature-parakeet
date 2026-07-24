from __future__ import annotations

from pathlib import Path

import pytest

from math_agent.agents.explainer import Explainer
from math_agent.agents.planner import Planner
from math_agent.agents.refiner import Refiner
from math_agent.agents.solver import Solver
from math_agent.agents.verifier import Verifier
from math_agent.schemas import Verification


class DummyClient:
    def __init__(self, response: str = "{}") -> None:
        self.response = response
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], **_: object) -> str:
        self.calls.append(messages)
        return self.response


def test_planner_mock_returns_structure() -> None:
    planner = Planner(client=DummyClient(), mock=True)
    result = planner.plan("2+2=?", {"recommended_solver": "general"})
    assert "problem_parse" in result
    assert "solution_plan" in result


def test_planner_rejects_duplicate_model_json_keys() -> None:
    planner = Planner(
        client=DummyClient('{"solution_plan":["unsafe"],"solution_plan":["accepted"]}'),
        mock=False,
    )

    result = planner.plan("2+2=?", {"recommended_solver": "general"})

    assert result["solution_plan"] != ["accepted"]
    assert "planner_non_json_fallback" in result["risk_points"]


def test_solver_mock_returns_boxed_answer() -> None:
    solver = Solver(client=DummyClient(), mock=True)
    out = solver.solve(
        "2+2=?", {"recommended_solver": "general"}, {"solution_plan": []}
    )
    assert "\\boxed{" in out


@pytest.mark.parametrize(
    ("solver_name", "expected_key"),
    [
        ("general", "solver_system"),
        ("program", "program_solver_system"),
        ("proof", "proof_solver_system"),
        ("optimization", "solver_system"),
    ],
)
def test_solver_select_prompt_key(solver_name: str, expected_key: str) -> None:
    solver = Solver(client=DummyClient(), mock=True)
    assert (
        solver._select_prompt_key({"recommended_solver": solver_name}) == expected_key
    )


def test_verifier_mock_returns_verification_passed() -> None:
    verifier = Verifier(client=DummyClient(), mock=True)
    res = verifier.verify("q", "draft", "42")
    assert isinstance(res, Verification)
    assert res.passed is True


def test_verifier_tool_check_requires_explicit_answer_evidence() -> None:
    verifier = Verifier(client=DummyClient(), mock=False)

    assert verifier._tool_verify("x = 12", "2") is None
    assert verifier._tool_verify("candidate values are 10 and 20", "[1, 2]") is None

    boxed = verifier._tool_verify(r"Therefore, \boxed{2}.", "2")
    explicit = verifier._tool_verify("Final answer: 2", "2")
    assert boxed is not None and boxed.passed is True
    assert explicit is not None and explicit.passed is True


def test_draft_final_consistency_cannot_bypass_question_verification() -> None:
    verifier = Verifier(client=DummyClient(response="not-json"), mock=False)

    result = verifier.verify(
        "What is 2+2?",
        "Final answer: 5",
        "5",
        {"problem_type": "calculation"},
    )

    assert result.passed is False
    assert result.method == "self_review"
    assert "Consistency diagnostics" in result.notes


@pytest.mark.parametrize("passed", [1, "yes", "on", 0])
def test_verifier_rejects_non_boolean_passed_values(passed: object) -> None:
    response = (
        '{"method":"self_review","passed":'
        + __import__("json").dumps(passed)
        + ',"notes":"claimed"}'
    )
    verifier = Verifier(client=DummyClient(response=response), mock=False)

    result = verifier.verify(
        "What is 2+2?", "Final answer: 999", "999", {"problem_type": "calculation"}
    )

    assert result.passed is False


def test_verifier_rejects_duplicate_model_json_keys() -> None:
    verifier = Verifier(
        client=DummyClient(
            '{"method":"self_review","passed":false,"passed":true,'
            '"notes":"ambiguous"}'
        ),
        mock=False,
    )

    result = verifier.verify(
        "What is 2+2?", "Final answer: 999", "999", {"problem_type": "calculation"}
    )

    assert result.passed is False
    assert "fallback" in result.notes.casefold()


def test_refiner_mock_not_crash() -> None:
    refiner = Refiner(client=DummyClient(), mock=True)
    out = refiner.refine("q", "draft", {"passed": True})
    assert out


def test_explainer_mock_non_empty() -> None:
    explainer = Explainer(client=DummyClient(), mock=True)
    out = explainer.explain("q", "solution", "42")
    assert isinstance(out, str)
    assert out.strip()


@pytest.mark.parametrize("agent_cls", [Planner, Solver, Verifier, Refiner, Explainer])
def test_agents_raise_on_missing_prompt_file(agent_cls: type) -> None:
    with pytest.raises(FileNotFoundError):
        agent_cls(
            client=DummyClient(),
            prompt_config_path=Path("configs/not_exist_prompts.yaml"),
            mock=True,
        )


def test_non_mock_agents_use_client_without_real_network() -> None:
    dummy = DummyClient(response='{"method":"self_review","passed":true,"notes":"ok"}')

    planner = Planner(client=dummy, mock=False)
    solver = Solver(client=dummy, mock=False)
    verifier = Verifier(client=dummy, mock=False)
    refiner = Refiner(client=dummy, mock=False)
    explainer = Explainer(client=dummy, mock=False)

    planner.plan("q", {"recommended_solver": "general"})
    solver.solve("q", {"recommended_solver": "general"}, {"solution_plan": []})
    res = verifier.verify("q", "draft", "42")
    refiner.refine("q", "draft", "feedback")
    explainer.explain("q", "solution", "42")

    assert isinstance(res, Verification)
    assert len(dummy.calls) >= 5
