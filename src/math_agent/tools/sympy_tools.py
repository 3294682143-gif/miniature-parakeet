from __future__ import annotations

from sympy import Eq, simplify, solve, sympify


def simplify_expression(expr: str) -> str:
    try:
        return str(simplify(sympify(expr)))
    except Exception as exc:
        return f"ERROR: unable to simplify expression ({exc})"


def check_equivalent(expr1: str, expr2: str) -> bool:
    try:
        lhs = sympify(expr1)
        rhs = sympify(expr2)
        return bool(simplify(lhs - rhs) == 0)
    except Exception:
        return False


def numeric_compare(a: str, b: str, tol: float = 1e-6) -> bool:
    try:
        av = float(sympify(a).evalf())
        bv = float(sympify(b).evalf())
        return abs(av - bv) <= tol
    except Exception:
        return False


def solve_equation(equation: str, variable: str = "x") -> str:
    try:
        symbol = sympify(variable)
        if "=" in equation:
            left, right = equation.split("=", 1)
            eq = Eq(sympify(left), sympify(right))
            result = solve(eq, symbol)
        else:
            result = solve(sympify(equation), symbol)
        return str(result)
    except Exception as exc:
        return f"ERROR: unable to solve equation ({exc})"
