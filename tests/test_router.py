from __future__ import annotations

from pathlib import Path

import pytest

from math_agent.agents.router import RouteInfo, Router


@pytest.mark.parametrize(
    ("question", "expected_domain"),
    [
        ("请解这个偏微分方程边值问题", "PDE"),
        ("Use residue theorem for contour integral", "ComplexAnalysis"),
        ("判断两个空间是否同胚并讨论compact性", "Topology"),
        ("线性规划：在约束下最大化目标函数", "Optimization"),
        ("求矩阵的eigenvalue并分析对应特征向量", "Algebra"),
        ("随机变量的期望与方差如何计算", "Probability"),
        ("证明素数与同余的一个结论", "NumberTheory"),
        ("求导数并计算极限", "Calculus"),
        ("这是一道历史题，不是数学", "Unknown"),
    ],
)
def test_domain_recognition(question: str, expected_domain: str) -> None:
    router = Router(mode="rule_based")
    result = router.route(question)
    assert result.domain == expected_domain


def test_proof_routes_to_proof_solver() -> None:
    router = Router(mode="rule_based")
    result = router.route("证明这个命题成立")
    assert result.problem_type == "proof"
    assert result.recommended_solver == "proof"
    assert result.needs_tool is False


def test_optimization_routes_to_optimization_solver() -> None:
    router = Router(mode="rule_based")
    result = router.route("在约束条件下最小化该函数")
    assert result.problem_type == "optimization"
    assert result.recommended_solver == "optimization"
    assert result.needs_tool is True


def test_calculation_routes_to_program_solver() -> None:
    router = Router(mode="rule_based")
    result = router.route("计算这个积分表达式的值")
    assert result.problem_type == "calculation"
    assert result.recommended_solver == "program"
    assert result.needs_tool is True


def test_confidence_out_of_range_should_fail() -> None:
    with pytest.raises(Exception):
        RouteInfo(
            domain="Calculus",
            problem_type="calculation",
            recommended_solver="program",
            needs_tool=True,
            confidence=1.5,
            reason="bad confidence",
        )


def test_rule_based_does_not_call_api(monkeypatch: pytest.MonkeyPatch) -> None:
    router = Router(mode="rule_based")

    def _boom(*args, **kwargs):
        raise AssertionError("chat should not be called in rule_based mode")

    monkeypatch.setattr(router.client, "chat", _boom)
    result = router.route("证明这个代数结论")
    assert result.problem_type == "proof"


class DummyLLMClient:
    def __init__(self, content: str):
        self.content = content
        self.last_messages = None

    def chat(self, messages):
        self.last_messages = messages
        return self.content


def test_llm_mode_with_mock_client_returns_valid_routeinfo() -> None:
    content = (
        '{"domain":"Calculus","problem_type":"calculation","recommended_solver":"program",'
        '"needs_tool":true,"confidence":0.88,"reason":"mocked"}'
    )
    client = DummyLLMClient(content)
    router = Router(mode="llm", client=client)
    result = router.route("求定积分")
    assert result.domain == "Calculus"
    assert result.recommended_solver == "program"


def test_llm_mode_reads_router_system_from_prompt_config(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompts.yaml"
    prompt_file.write_text("router_system: |\n  ROUTER-SYS-PROMPT\n", encoding="utf-8")
    content = (
        '{"domain":"Calculus","problem_type":"calculation","recommended_solver":"program",'
        '"needs_tool":true,"confidence":0.88,"reason":"mocked"}'
    )
    client = DummyLLMClient(content)
    router = Router(mode="llm", client=client, prompt_config_path=prompt_file)

    router.route("compute integral")

    assert client.last_messages is not None
    assert client.last_messages[0]["role"] == "system"
    assert "ROUTER-SYS-PROMPT" in client.last_messages[0]["content"]


def test_llm_invalid_output_fallback_to_rule_based() -> None:
    router = Router(mode="llm", client=DummyLLMClient("not-json"))
    result = router.route("证明素数有无穷多个")
    assert result.domain == "NumberTheory"
    assert result.recommended_solver == "proof"


def test_llm_missing_router_system_fallback_to_rule_based(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompts.yaml"
    prompt_file.write_text("planner_system: 'x'\n", encoding="utf-8")
    router = Router(mode="llm", client=DummyLLMClient("should-not-be-used"), prompt_config_path=prompt_file)

    result = router.route("证明素数有无穷多个")
    assert result.domain == "NumberTheory"
    assert result.recommended_solver == "proof"


def test_llm_missing_prompt_file_fallback_to_rule_based(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-prompts.yaml"
    router = Router(mode="llm", client=DummyLLMClient("should-not-be-used"), prompt_config_path=missing_path)

    result = router.route("证明素数有无穷多个")
    assert result.domain == "NumberTheory"
    assert result.recommended_solver == "proof"
