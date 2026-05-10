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


def test_solver_mock_returns_boxed_answer() -> None:
    solver = Solver(client=DummyClient(), mock=True)
    out = solver.solve("2+2=?", {"recommended_solver": "general"}, {"solution_plan": []})
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
    assert solver._select_prompt_key({"recommended_solver": solver_name}) == expected_key


def test_verifier_mock_returns_verification_passed() -> None:
    verifier = Verifier(client=DummyClient(), mock=True)
    res = verifier.verify("q", "draft", "42")
    assert isinstance(res, Verification)
    assert res.passed is True


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
        agent_cls(client=DummyClient(), prompt_config_path=Path("configs/not_exist_prompts.yaml"), mock=True)


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
