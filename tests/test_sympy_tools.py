from math_agent.tools.sympy_tools import check_equivalent, numeric_compare, simplify_expression, solve_equation


def test_simplify_expression_identity() -> None:
    simplified = simplify_expression("sin(x)**2 + cos(x)**2")
    assert check_equivalent(simplified, "1")


def test_check_equivalent() -> None:
    assert check_equivalent("x+x", "2*x") is True


def test_numeric_compare() -> None:
    assert numeric_compare("0.3333333", "1/3") is True


def test_solve_equation() -> None:
    result = solve_equation("x**2-1=0", "x")
    assert "-1" in result
    assert "1" in result


def test_parse_error_does_not_crash() -> None:
    assert check_equivalent("x+", "2*x") is False
