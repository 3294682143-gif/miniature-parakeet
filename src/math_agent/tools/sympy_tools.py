from __future__ import annotations

import re

from sympy import Eq, simplify, solve, sympify
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)


def _parse_math_expr(expr: str):
    return parse_expr(expr, transformations=_TRANSFORMS, evaluate=True)


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
        symbol = _parse_math_expr(variable)
        if "=" in equation:
            left, right = equation.split("=", 1)
            eq = Eq(_parse_math_expr(left), _parse_math_expr(right))
            result = solve(eq, symbol)
        else:
            result = solve(_parse_math_expr(equation), symbol)
        if isinstance(result, list) and len(result) == 1:
            return f"{variable.strip()}={result[0]}"
        return re.sub(r"\s+", "", str(result))
    except Exception as exc:
        return f"ERROR: unable to solve equation ({exc})"
