from math_agent.pipeline import MathAgentPipeline
from math_agent.schemas import SolveResult


def test_enable_tools_false_no_tool_trace_success():
    result = MathAgentPipeline(mock=True, enable_tools=False).solve("计算 2+3", "t1")
    assert isinstance(result, SolveResult)
    assert not any(t.tool in {"python", "sympy"} for t in result.tool_trace)


def test_enable_tools_true_arithmetic_boxed_5():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("计算 2+3", "t2")
    assert result.final_answer.value == "5"
    assert result.final_answer.boxed == "\\boxed{5}"
    assert any(t.status == "success" and t.tool == "python" for t in result.tool_trace)


def test_enable_tools_true_simplify_expression():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("化简 sin(x)^2 + cos(x)^2", "t3")
    assert result.final_answer.value == "1"
    assert any(t.status == "success" and t.tool == "sympy" for t in result.tool_trace)


def test_enable_tools_skip_no_crash():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("请解释什么是群", "t4")
    assert isinstance(result, SolveResult)
    assert any(t.status == "skipped" for t in result.tool_trace)


def test_enable_tools_fail_returns_valid_result():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("求解 x**2 - 1 =", "t5")
    assert isinstance(result, SolveResult)
    assert result.status in {"success", "partial"}
    assert any(t.status in {"fail", "skipped", "success"} for t in result.tool_trace)


def test_tools_result_updates_visible_steps_consistently():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("计算 2+3", "t6")
    assert result.final_answer.boxed == "\\boxed{5}"
    assert "\\boxed{5}" in result.visible_solution_steps[0]
    assert result.verification.passed is True


def test_enable_tools_equation_has_final_answer_and_success():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("解方程 2x+5=13", "eq1")
    assert result.status == "success"
    assert result.final_answer.value
    assert "4" in result.final_answer.value or "4" in result.final_answer.boxed
    assert "**" not in result.final_answer.boxed
    assert "\n" not in result.final_answer.boxed
    assert any(t.tool == "sympy" and t.status == "success" for t in result.tool_trace)
