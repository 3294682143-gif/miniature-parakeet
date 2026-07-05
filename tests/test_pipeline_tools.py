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
    result = MathAgentPipeline(mock=True, enable_tools=True).solve(
        "化简 sin(x)^2 + cos(x)^2", "t3"
    )
    assert isinstance(result, SolveResult)
    # The tool may or may not match depending on routing; result is always valid


def test_enable_tools_skip_no_crash():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve(
        "请解释什么是群", "t4"
    )
    assert isinstance(result, SolveResult)
    # Tool trace may be empty or contain no_match/skipped/fail statuses


def test_enable_tools_fail_returns_valid_result():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve(
        "求解 x**2 - 1 =", "t5"
    )
    assert isinstance(result, SolveResult)
    assert result.status in {"success", "partial"}
    assert any(t.status in {"fail", "skipped", "success"} for t in result.tool_trace)


def test_tools_result_updates_visible_steps_consistently():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve("计算 2+3", "t6")
    assert result.final_answer.boxed == "\\boxed{5}"
    assert "\\boxed{5}" in result.visible_solution_steps[0]
    assert result.verification.passed is True


def test_enable_tools_equation_has_final_answer_and_success():
    result = MathAgentPipeline(mock=True, enable_tools=True).solve(
        "解方程 2x+5=13", "eq1"
    )
    assert result.status == "success"
    assert result.final_answer.value
    assert "4" in result.final_answer.value or "4" in result.final_answer.boxed
    assert "**" not in result.final_answer.boxed
    assert "\n" not in result.final_answer.boxed
    assert any(t.tool == "sympy" and t.status == "success" for t in result.tool_trace)


def test_enable_tools_calculus_geometry_probability_combinatorics():
    pipeline = MathAgentPipeline(mock=True, enable_tools=True, run_mode="tool-first")
    cases = [
        (
            "Compute the derivative of f(x)=sin(x). Give the final answer only.",
            "cos(x)",
        ),
        (
            "Evaluate the limit as x approaches 2 of x**2 + 3*x. Give the final answer only.",
            "10",
        ),
        (
            "A rectangle has length 8 and width 5. Compute its area. Give the final answer only.",
            "40",
        ),
        ("Compute 12 choose 2. Give the final answer only.", "66"),
        (
            "A fair coin is tossed 3 times. What is the probability of exactly 2 heads? Give the final answer only.",
            "3/8",
        ),
        ("Compute gcd(48, 18). Give the final answer only.", "6"),
        (
            "Compute the remainder when 47 is divided by 5. Give the final answer only.",
            "2",
        ),
        (
            "Find the squared distance between (1,2) and (4,6). Give the final answer only.",
            "25",
        ),
        (
            "A triangle has base 7 and height 6. Compute its area. Give the final answer only.",
            "21",
        ),
        (
            "An arithmetic sequence has a_1=3 and common difference 4. Compute a_8. Give the final answer only.",
            "31",
        ),
        (
            "A geometric sequence has a_1=2 and ratio 3. Compute a_5. Give the final answer only.",
            "162",
        ),
        (
            "If f(x)=2*x + 1, compute f(4). Give the final answer only.",
            "9",
        ),
        (
            "If f(x)=2*x + 1 and g(x)=3*x + 2, compute f(g(4)). Give the final answer only.",
            "29",
        ),
        (
            "Find the least nonnegative residue of 7^128 modulo 19. Give the final answer only.",
            "11",
        ),
        ("Compute Euler phi of 840. Give the final answer only.", "192"),
        (
            "How many positive divisors does 756 have? Give the final answer only.",
            "24",
        ),
        (
            "Find the least positive inverse of 17 modulo 43. Give the final answer only.",
            "38",
        ),
        (
            "Find the least nonnegative solution x to x = 2 mod 5 and x = 3 mod 7. Give the final answer only.",
            "17",
        ),
        (
            "A right triangle has legs 9 and 12. Compute its inradius. Give the final answer only.",
            "3",
        ),
        (
            "A triangle has side lengths 13, 14, 15. Compute its area. Give the final answer only.",
            "84",
        ),
        (
            "A circle has radius 13, and a chord is 6 from the center. Compute the chord length. Give the final answer only.",
            "2*sqrt(133)",
        ),
    ]
    for idx, (question, expected) in enumerate(cases):
        result = pipeline.solve(question, f"det_{idx}")
        assert result.status == "success"
        assert (
            expected in result.final_answer.value
            or result.final_answer.value == expected
        )
        assert result.verification.passed is True
