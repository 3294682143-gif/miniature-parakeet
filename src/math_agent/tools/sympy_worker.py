from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 8 * 1024
MAX_RESULT_CHARS = 32_768
MEMORY_LIMIT_BYTES = 384 * 1024 * 1024
CPU_LIMIT_SECONDS = 4


def _apply_posix_limits() -> None:
    if os.name == "nt":
        return
    try:
        import resource

        setrlimit = getattr(resource, "setrlimit", None)
        rlimit_as = getattr(resource, "RLIMIT_AS", None)
        rlimit_cpu = getattr(resource, "RLIMIT_CPU", None)
        if not callable(setrlimit) or rlimit_as is None or rlimit_cpu is None:
            raise RuntimeError("resource isolation is unavailable")
        setrlimit(rlimit_as, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
        setrlimit(rlimit_cpu, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS))
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError("resource isolation is unavailable") from exc


def _load_math_modules() -> tuple[Any, Any]:
    source_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(source_root))
    import sympy as sp  # type: ignore[import-untyped]

    from math_agent.tools.safe_sympy import parse_math_expression

    return sp, parse_math_expression


def _format(value: Any, sp: Any) -> str:
    if _contains_nonfinite(value, sp):
        raise ValueError("result is outside the finite domain")
    rendered = re.sub(r"\s+", "", str(sp.simplify(value)))
    if len(rendered) > MAX_RESULT_CHARS:
        raise ValueError("result exceeds the safe size limit")
    return rendered


def _contains_nonfinite(value: Any, sp: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(_contains_nonfinite(item, sp) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_nonfinite(key, sp) or _contains_nonfinite(item, sp)
            for key, item in value.items()
        )
    try:
        return any(
            value == item or bool(value.has(item))
            for item in (sp.oo, -sp.oo, sp.zoo, sp.nan)
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _require_strings(arguments: Any, count: int) -> list[Any]:
    if not isinstance(arguments, list) or len(arguments) != count:
        raise ValueError("arguments do not match the safe schema")
    return arguments


def _execute(operation: str, arguments: Any) -> str | bool:
    sp, parse = _load_math_modules()
    if operation == "simplify":
        (expr,) = _require_strings(arguments, 1)
        return _format(sp.simplify(parse(expr)), sp)
    if operation == "differentiate":
        expr, variable = _require_strings(arguments, 2)
        return _format(sp.diff(parse(expr), parse(variable)), sp)
    if operation == "limit":
        expr, variable, point = _require_strings(arguments, 3)
        return _format(sp.limit(parse(expr), parse(variable), parse(point)), sp)
    if operation == "integrate":
        expr, variable, lower, upper = _require_strings(arguments, 4)
        symbol = parse(variable)
        parsed = parse(expr)
        if lower is not None and upper is not None:
            return _format(
                sp.integrate(parsed, (symbol, parse(lower), parse(upper))), sp
            )
        if lower is not None or upper is not None:
            raise ValueError("integration bounds must be paired")
        return _format(sp.integrate(parsed, symbol), sp)
    if operation == "equivalent":
        expr1, expr2 = _require_strings(arguments, 2)
        return bool(sp.simplify(parse(expr1) - parse(expr2)) == 0)
    if operation == "numeric_compare":
        a, b, tolerance = _require_strings(arguments, 3)
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
            raise ValueError("tolerance is invalid")
        av = float(parse(a).evalf())
        bv = float(parse(b).evalf())
        if not __import__("math").isfinite(av) or not __import__("math").isfinite(bv):
            raise ValueError("numeric value is outside the finite domain")
        return abs(av - bv) <= float(tolerance)
    if operation == "solve":
        equation, variable = _require_strings(arguments, 2)
        symbol = parse(variable)
        if not isinstance(symbol, sp.Symbol):
            raise ValueError("solve variable must be a single symbol")
        if "=" in equation:
            left, right = equation.split("=", 1)
            parsed_left, parsed_right = parse(left), parse(right)
            result = sp.solve(sp.Eq(parsed_left, parsed_right), symbol)
        else:
            parsed_left, parsed_right = parse(equation), sp.Integer(0)
            result = sp.solve(parsed_left, symbol)
        if (
            not isinstance(result, list)
            or not result
            or _contains_nonfinite(result, sp)
        ):
            raise ValueError("equation has no finite supported solution")
        for solution in result:
            residual = sp.simplify((parsed_left - parsed_right).subs(symbol, solution))
            if residual != 0:
                raise ValueError("solution failed substitution")
        if isinstance(result, list) and len(result) == 1:
            rendered = f"{str(variable).strip()}={result[0]}"
            if len(rendered) > MAX_RESULT_CHARS:
                raise ValueError("result exceeds the safe size limit")
            return rendered
        rendered = re.sub(r"\s+", "", str(result))
        if len(rendered) > MAX_RESULT_CHARS:
            raise ValueError("result exceeds the safe size limit")
        return rendered
    raise ValueError("operation is not allowed")


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds the safe size limit")
        source_root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(source_root))
        from math_agent.io_utils import strict_json_loads

        request = strict_json_loads(raw.decode("utf-8", errors="strict"))
        if not isinstance(request, dict):
            raise ValueError("request does not match the safe schema")
        operation = request.get("operation")
        if not isinstance(operation, str):
            raise ValueError("operation does not match the safe schema")
        _apply_posix_limits()
        value = _execute(operation, request.get("arguments"))
        response = {"ok": True, "value": value}
    except BaseException:
        response = {"ok": False, "error": "operation rejected"}
    encoded = json.dumps(
        response, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_RESULT_CHARS * 2:
        encoded = b'{"ok":false,"error":"response rejected"}'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
