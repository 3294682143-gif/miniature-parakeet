from __future__ import annotations

import math
import re
from typing import Any

import sympy as sp  # type: ignore[import-untyped]
from sympy.parsing.sympy_parser import (  # type: ignore[import-untyped]
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

MAX_EXPRESSION_LENGTH = 512
MAX_EXPRESSION_TOKENS = 256
MAX_EXPRESSION_NODES = 512
MAX_SYMBOLS = 32
MAX_INTEGER_DIGITS = 64
MAX_ABS_NUMERIC_EXPONENT = 1_000
MAX_PARENTHESIS_DEPTH = 32
MAX_EXPONENT_VALIDATION_OPERATIONS = MAX_EXPRESSION_NODES * 8


class UnsafeMathExpressionError(ValueError):
    """Raised when an expression is outside the supported safe-math grammar."""


_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_IDENTIFIER = r"[A-Za-z][A-Za-z0-9_]*"
_TOKEN_RE = re.compile(
    rf"\s*(?:(?P<number>{_NUMBER})|(?P<identifier>{_IDENTIFIER})|"
    r"(?P<operator>\*\*|[+\-*/^(),]))"
)
_RESERVED_IDENTIFIERS = {
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "false",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "none",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "true",
    "try",
    "while",
    "with",
    "yield",
}
_ALLOWED_FUNCTIONS: dict[str, Any] = {
    "Abs": sp.Abs,
    "acos": sp.acos,
    "asin": sp.asin,
    "atan": sp.atan,
    "ceiling": sp.ceiling,
    "cos": sp.cos,
    "cosh": sp.cosh,
    "exp": sp.exp,
    "floor": sp.floor,
    "ln": sp.log,
    "log": sp.log,
    "sin": sp.sin,
    "sinh": sp.sinh,
    "sqrt": sp.sqrt,
    "tan": sp.tan,
    "tanh": sp.tanh,
}
_ALLOWED_CONSTANTS: dict[str, Any] = {
    "E": sp.E,
    "I": sp.I,
    "e": sp.E,
    "oo": sp.oo,
    "pi": sp.pi,
}
_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": {},
    "Add": sp.Add,
    "Float": sp.Float,
    "Integer": sp.Integer,
    "Mul": sp.Mul,
    "Pow": sp.Pow,
    "Rational": sp.Rational,
    "Symbol": sp.Symbol,
    **_ALLOWED_FUNCTIONS,
    **_ALLOWED_CONSTANTS,
}
_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)


def _validated_tokens(expression: str) -> list[tuple[str, str]]:
    if not isinstance(expression, str):
        raise UnsafeMathExpressionError("expression must be a string")
    text = expression.strip()
    if not text:
        raise UnsafeMathExpressionError("expression is empty")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise UnsafeMathExpressionError("expression is too long")

    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if match is None:
            if text[position:].strip() == "":
                break
            raise UnsafeMathExpressionError(
                f"unsupported syntax at character {position}"
            )
        kind = match.lastgroup
        if kind is None:
            raise UnsafeMathExpressionError("unable to tokenize expression")
        value = match.group(kind)
        tokens.append((kind, value))
        if len(tokens) > MAX_EXPRESSION_TOKENS:
            raise UnsafeMathExpressionError("expression has too many tokens")
        position = match.end()

    for index, (kind, value) in enumerate(tokens):
        if kind == "number":
            number_parts = re.split(r"[eE]", value, maxsplit=1)
            mantissa = number_parts[0]
            digits = sum(character.isdigit() for character in mantissa)
            if digits > MAX_INTEGER_DIGITS:
                raise UnsafeMathExpressionError("numeric literal is too large")
            if len(number_parts) == 2:
                scientific_exponent = int(number_parts[1])
                if abs(scientific_exponent) > MAX_ABS_NUMERIC_EXPONENT:
                    raise UnsafeMathExpressionError("scientific exponent is too large")
        elif kind == "identifier":
            if value.casefold() in _RESERVED_IDENTIFIERS:
                raise UnsafeMathExpressionError("reserved identifier is not allowed")
            next_value = tokens[index + 1][1] if index + 1 < len(tokens) else None
            if next_value == "(" and value not in _ALLOWED_FUNCTIONS:
                raise UnsafeMathExpressionError(
                    f"function {value!r} is not in the safe allowlist"
                )
    depth = 0
    for _, value in tokens:
        if value == "(":
            depth += 1
            if depth > MAX_PARENTHESIS_DEPTH:
                raise UnsafeMathExpressionError("expression nesting is too deep")
        elif value == ")":
            depth -= 1
            if depth < 0:
                raise UnsafeMathExpressionError("parentheses are unbalanced")
    if depth:
        raise UnsafeMathExpressionError("parentheses are unbalanced")
    return tokens


def _consume_exponent_validation_budget(budget: list[int], amount: int = 1) -> None:
    budget[0] -= amount
    if budget[0] < 0:
        raise UnsafeMathExpressionError("exponent normalization is too complex")


def _validate_numeric_exponent(exponent: sp.Expr) -> None:
    try:
        components = exponent.as_real_imag()
    except (AttributeError, TypeError, ValueError):
        raise UnsafeMathExpressionError("numeric exponent is not bounded")
    component_values: list[float] = []
    for component in components:
        if component.is_number is not True or component.is_real is not True:
            raise UnsafeMathExpressionError("numeric exponent is not bounded")
        try:
            component_value = float(component)
        except (TypeError, ValueError, OverflowError):
            raise UnsafeMathExpressionError("numeric exponent is not bounded")
        if not math.isfinite(component_value):
            raise UnsafeMathExpressionError("numeric exponent is not bounded")
        component_values.append(component_value)
    if math.hypot(*component_values) > MAX_ABS_NUMERIC_EXPONENT:
        raise UnsafeMathExpressionError("numeric exponent is too large")


def _validate_numeric_exponent_nodes(exponent: sp.Expr, budget: list[int]) -> None:
    for candidate in sp.preorder_traversal(exponent):
        _consume_exponent_validation_budget(budget)
        if isinstance(candidate, sp.Expr) and candidate.is_number is True:
            _validate_numeric_exponent(candidate)


def _bounded_normalize_exponent(exponent: sp.Expr, budget: list[int]) -> sp.Expr:
    """Combine only bounded Add/Mul nodes; never run general simplification."""

    _consume_exponent_validation_budget(budget)
    normalized_arguments: list[sp.Expr] = []
    for argument in exponent.args:
        if not isinstance(argument, sp.Expr):
            raise UnsafeMathExpressionError("exponent contains a non-scalar node")
        normalized_arguments.append(_bounded_normalize_exponent(argument, budget))
    if isinstance(exponent, sp.Add):
        normalized = sp.Add(*normalized_arguments)
    elif isinstance(exponent, sp.Mul):
        normalized = sp.Mul(*normalized_arguments)
    elif isinstance(exponent, sp.Pow):
        normalized = sp.Pow(*normalized_arguments)
    elif isinstance(exponent, sp.Function):
        normalized = exponent.func(*normalized_arguments)
    else:
        return exponent
    if not isinstance(normalized, sp.Expr):
        raise UnsafeMathExpressionError("normalized exponent is not scalar")

    normalized_nodes = list(sp.preorder_traversal(normalized))
    _consume_exponent_validation_budget(budget, len(normalized_nodes))
    if len(normalized_nodes) > MAX_EXPRESSION_NODES:
        raise UnsafeMathExpressionError("normalized exponent is too complex")
    return normalized


def _validate_parsed_expression(expression: sp.Expr) -> None:
    nodes = list(sp.preorder_traversal(expression))
    if len(nodes) > MAX_EXPRESSION_NODES:
        raise UnsafeMathExpressionError("expression is too complex")
    if len(expression.free_symbols) > MAX_SYMBOLS:
        raise UnsafeMathExpressionError("expression has too many symbols")

    allowed_function_types = set(_ALLOWED_FUNCTIONS.values())
    for function in expression.atoms(sp.Function):
        if function.func not in allowed_function_types:
            raise UnsafeMathExpressionError("expression contains an unsafe function")

    exponent_validation_budget = [MAX_EXPONENT_VALIDATION_OPERATIONS]
    for node in nodes:
        if not isinstance(node, sp.Pow):
            continue
        exponent = node.exp
        _validate_numeric_exponent_nodes(exponent, exponent_validation_budget)
        if exponent.is_number is not True:
            normalized = _bounded_normalize_exponent(
                exponent, exponent_validation_budget
            )
            _validate_numeric_exponent_nodes(normalized, exponent_validation_budget)


def parse_math_expression(expression: str) -> sp.Expr:
    """Parse the supported math grammar without exposing Python builtins."""

    _validated_tokens(expression)
    local_dict = dict(_ALLOWED_CONSTANTS)

    try:
        parsed = parse_expr(
            expression,
            transformations=_TRANSFORMATIONS,
            local_dict=local_dict,
            global_dict=dict(_SAFE_GLOBALS),
            evaluate=False,
        )
    except Exception as exc:
        raise UnsafeMathExpressionError("unable to parse safe math expression") from exc
    if not isinstance(parsed, sp.Expr):
        raise UnsafeMathExpressionError("expression did not produce a scalar value")
    _validate_parsed_expression(parsed)
    return parsed
