from __future__ import annotations

import re
from typing import Any

from sympy import (  # type: ignore[import-untyped]
    Eq,
    binomial,
    diff,
    integrate,
    limit,
    simplify,
    solve,
    sympify,
)
from sympy.parsing.sympy_parser import (  # type: ignore[import-untyped]
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)
_LOCAL_SYMBOLS = {"e": sympify("E"), "E": sympify("E")}


def _parse_math_expr(expr: str):
    return parse_expr(expr, transformations=_TRANSFORMS, evaluate=True)


def simplify_expression(expr: str) -> str:
    try:
        return str(simplify(_parse_math_expr(expr)))
    except Exception as exc:
        return f"ERROR: unable to simplify expression ({exc})"


def _format_result(value: Any) -> str:
    return re.sub(r"\s+", "", str(simplify(value)))


def differentiate_expression(expr: str, variable: str = "x") -> str:
    try:
        symbol = _parse_math_expr(variable)
        return _format_result(diff(_parse_math_expr(expr), symbol))
    except Exception as exc:
        return f"ERROR: unable to differentiate expression ({exc})"


def limit_expression(expr: str, variable: str = "x", point: str = "0") -> str:
    try:
        symbol = _parse_math_expr(variable)
        return _format_result(
            limit(_parse_math_expr(expr), symbol, _parse_math_expr(point))
        )
    except Exception as exc:
        return f"ERROR: unable to compute limit ({exc})"


def integrate_expression(
    expr: str,
    variable: str = "x",
    lower: str | None = None,
    upper: str | None = None,
) -> str:
    try:
        symbol = _parse_math_expr(variable)
        parsed = _parse_math_expr(expr)
        if lower is not None and upper is not None:
            return _format_result(
                integrate(
                    parsed,
                    (symbol, _parse_math_expr(lower), _parse_math_expr(upper)),
                )
            )
        return _format_result(integrate(parsed, symbol))
    except Exception as exc:
        return f"ERROR: unable to integrate expression ({exc})"


def choose(n: str | int, k: str | int) -> str:
    try:
        return str(int(binomial(int(n), int(k))))
    except Exception as exc:
        return f"ERROR: unable to compute combination ({exc})"


def check_equivalent(expr1: str, expr2: str) -> bool:
    try:
        lhs = _parse_math_expr(expr1)
        rhs = _parse_math_expr(expr2)
        return bool(simplify(lhs - rhs) == 0)
    except Exception:
        return False


def numeric_compare(a: str, b: str, tol: float = 1e-6) -> bool:
    try:
        av = float(_parse_math_expr(a).evalf())
        bv = float(_parse_math_expr(b).evalf())
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
