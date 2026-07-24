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


@pytest.mark.parametrize(
    ("question", "expected_domain"),
    [
        ("讨论这个拓扑空间是否紧致并判断是否同胚", "Topology"),
        ("求这个矩阵的特征值和特征向量", "Algebra"),
        ("随机变量的期望和方差怎么算", "Probability"),
        ("在线性规划约束下最大化目标函数", "Optimization"),
        ("求这个函数的导数和极限", "Calculus"),
        ("用留数定理计算这个围道积分", "ComplexAnalysis"),
        ("分析偏微分方程的边界条件", "PDE"),
        ("求三角形的面积和内切圆半径", "Geometry"),
    ],
)
def test_clear_chinese_domain_keywords_route(
    question: str, expected_domain: str
) -> None:
    result = Router(mode="rule_based").route(question)
    assert result.domain == expected_domain


def test_proof_routes_to_proof_solver() -> None:
    router = Router(mode="rule_based")
    result = router.route("证明这个命题成立")
    assert result.problem_type == "proof"
    assert result.recommended_solver == "proof"
    assert result.needs_tool is False


def test_proof_intent_overrides_domain_specific_keywords() -> None:
    router = Router(mode="rule_based")
    result = router.route("Prove that for any integer n, n^3 - n is divisible by 6.")
    assert result.problem_type == "proof"
    assert result.recommended_solver == "proof"
    assert result.needs_tool is False


def test_operations_research_linear_program_routes_to_proof_solver() -> None:
    router = Router(mode="rule_based")
    result = router.route(
        "Prove briefly that a linear program over a nonempty bounded polytope "
        "has an optimal solution at an extreme point."
    )
    assert result.domain == "OperationsResearch"
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


def test_equation_question_routes_not_unknown() -> None:
    router = Router(mode="rule_based")
    result = router.route("解方程 2x+5=13")
    assert result.problem_type == "calculation"
    assert result.recommended_solver in {"program", "general"}


@pytest.mark.parametrize(
    ("question", "expected_domain", "expected_type"),
    [
        ("Compute gcd(48, 18). Give the final answer only.", "NumberTheory", "gcd"),
        (
            "A fair coin is tossed 5 times. What is the probability of exactly 2 heads?",
            "Probability",
            "binomial_probability",
        ),
        (
            "An arithmetic sequence has a_1=3 and common difference 4. Compute a_8.",
            "Recurrence",
            "arithmetic_sequence",
        ),
        (
            "If f(x)=2*x + 1, compute f(4). Give the final answer only.",
            "Functions",
            "function_evaluation",
        ),
        (
            "Find the squared distance between (1,2) and (4,6). Give the final answer only.",
            "Geometry",
            "coordinate_geometry",
        ),
        (
            "Find the least nonnegative residue of 7^128 modulo 19. Give the final answer only.",
            "NumberTheory",
            "modular_exponent",
        ),
        (
            "Compute Euler phi of 840. Give the final answer only.",
            "NumberTheory",
            "totient",
        ),
        (
            "A right triangle has legs 9 and 12. Compute its inradius. Give the final answer only.",
            "Geometry",
            "inradius",
        ),
        (
            "A circle has radius 13, and a chord is 6 from the center. Compute the chord length. Give the final answer only.",
            "Geometry",
            "chord_length",
        ),
    ],
)
def test_expanded_domain_and_problem_type_rules(
    question: str, expected_domain: str, expected_type: str
) -> None:
    result = Router(mode="rule_based").route(question)
    assert result.domain == expected_domain
    assert result.problem_type == expected_type
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


def test_llm_duplicate_json_keys_fallback_to_rule_based() -> None:
    content = (
        '{"domain":"Calculus","domain":"Geometry","problem_type":"calculation",'
        '"recommended_solver":"program","needs_tool":true,'
        '"confidence":0.88,"reason":"ambiguous"}'
    )
    router = Router(mode="llm", client=DummyLLMClient(content))

    result = router.route("compute integral")

    assert result.domain == "Calculus"
    assert result.reason != "ambiguous"


def test_llm_missing_router_system_fallback_to_rule_based(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompts.yaml"
    prompt_file.write_text("planner_system: 'x'\n", encoding="utf-8")
    router = Router(
        mode="llm",
        client=DummyLLMClient("should-not-be-used"),
        prompt_config_path=prompt_file,
    )

    result = router.route("证明素数有无穷多个")
    assert result.domain == "NumberTheory"
    assert result.recommended_solver == "proof"


def test_llm_missing_prompt_file_fallback_to_rule_based(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-prompts.yaml"
    router = Router(
        mode="llm",
        client=DummyLLMClient("should-not-be-used"),
        prompt_config_path=missing_path,
    )

    result = router.route("证明素数有无穷多个")
    assert result.domain == "NumberTheory"
    assert result.recommended_solver == "proof"
