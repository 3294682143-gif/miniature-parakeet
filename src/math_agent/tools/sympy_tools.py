from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from math_agent.io_utils import strict_json_loads
from math_agent.process_isolation import (
    WindowsJobLimits,
    assign_windows_job_limits,
    isolated_process_slot,
)

MAX_COMBINATION_INPUT = 10**18
MAX_COMBINATION_TERMS = 10_000
MAX_COMBINATION_RESULT_BITS = 32_768
MAX_SYMPY_REQUEST_BYTES = 8 * 1024
MAX_SYMPY_RESPONSE_BYTES = 64 * 1024
SYMPY_WALL_TIMEOUT_SECONDS = 2.5
SYMPY_MEMORY_LIMIT_BYTES = 384 * 1024 * 1024


def _worker_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _run_isolated_without_capacity_guard(operation: str, arguments: list[Any]) -> Any:
    request = json.dumps(
        {"operation": operation, "arguments": arguments},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(request) > MAX_SYMPY_REQUEST_BYTES:
        raise ValueError("request exceeds the safe size limit")

    worker = Path(__file__).with_name("sympy_worker.py")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process: subprocess.Popen[bytes] | None = None
    job: WindowsJobLimits | None = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-E", str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_worker_environment(),
            creationflags=creationflags,
        )
        if os.name == "nt":
            job = assign_windows_job_limits(
                process.pid,
                memory_limit_bytes=SYMPY_MEMORY_LIMIT_BYTES,
                cpu_limit_seconds=4,
            )
            if job is None:
                process.kill()
                process.wait(timeout=1)
                raise RuntimeError("resource isolation is unavailable")
        try:
            stdout, _ = process.communicate(
                input=request, timeout=SYMPY_WALL_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise TimeoutError("operation exceeded the safe time limit") from None
        if process.returncode != 0:
            raise RuntimeError("isolated operation failed")
        if len(stdout) > MAX_SYMPY_RESPONSE_BYTES:
            raise ValueError("response exceeds the safe size limit")
        response = strict_json_loads(stdout.decode("utf-8", errors="strict"))
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise ValueError("isolated operation was rejected")
        value = response.get("value")
        if not isinstance(value, (str, bool, int, float)) or isinstance(value, complex):
            raise ValueError("isolated operation returned an invalid value")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("isolated operation returned a non-finite value")
        return value
    except (OSError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise RuntimeError("isolated operation failed") from exc
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        if job is not None:
            job.close()


def _run_isolated(operation: str, arguments: list[Any]) -> Any:
    with isolated_process_slot():
        return _run_isolated_without_capacity_guard(operation, arguments)


def _error(action: str, exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        reason = "safe time limit exceeded"
    elif isinstance(exc, (ValueError, RuntimeError, OSError)):
        reason = "safe resource policy rejected the operation"
    else:
        reason = "operation failed"
    return f"ERROR: unable to {action} ({reason})"


def simplify_expression(expr: str) -> str:
    try:
        return str(_run_isolated("simplify", [expr]))
    except BaseException as exc:
        return _error("simplify expression", exc)


def differentiate_expression(expr: str, variable: str = "x") -> str:
    try:
        return str(_run_isolated("differentiate", [expr, variable]))
    except BaseException as exc:
        return _error("differentiate expression", exc)


def limit_expression(expr: str, variable: str = "x", point: str = "0") -> str:
    try:
        return str(_run_isolated("limit", [expr, variable, point]))
    except BaseException as exc:
        return _error("compute limit", exc)


def integrate_expression(
    expr: str,
    variable: str = "x",
    lower: str | None = None,
    upper: str | None = None,
) -> str:
    try:
        return str(_run_isolated("integrate", [expr, variable, lower, upper]))
    except BaseException as exc:
        return _error("integrate expression", exc)


def _bounded_int(value: str | int) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("integer input is invalid")
    text = str(value)
    if len(text) > 20 or not text.isascii() or not text.isdigit():
        raise ValueError("integer input is invalid")
    parsed = int(text)
    if parsed > MAX_COMBINATION_INPUT:
        raise ValueError("integer input exceeds the safe limit")
    return parsed


def choose(n: str | int, k: str | int) -> str:
    try:
        parsed_n = _bounded_int(n)
        parsed_k = _bounded_int(k)
        if parsed_k > parsed_n:
            raise ValueError("k must not exceed n")
        terms = min(parsed_k, parsed_n - parsed_k)
        if terms > MAX_COMBINATION_TERMS:
            raise ValueError("combination requires too many terms")
        estimated_bits = sum(
            math.log2(parsed_n - index) - math.log2(index + 1) for index in range(terms)
        )
        if estimated_bits > MAX_COMBINATION_RESULT_BITS:
            raise ValueError("combination result exceeds the safe limit")
        result = math.comb(parsed_n, parsed_k)
        if result.bit_length() > MAX_COMBINATION_RESULT_BITS:
            raise ValueError("combination result exceeds the safe limit")
        return str(result)
    except (ArithmeticError, TypeError, ValueError) as exc:
        return _error("compute combination", exc)


def check_equivalent(expr1: str, expr2: str) -> bool:
    try:
        return _run_isolated("equivalent", [expr1, expr2]) is True
    except BaseException:
        return False


def numeric_compare(a: str, b: str, tol: float = 1e-6) -> bool:
    try:
        if (
            isinstance(tol, bool)
            or not isinstance(tol, (int, float))
            or not math.isfinite(float(tol))
            or not 0 <= float(tol) <= 1
        ):
            return False
        return _run_isolated("numeric_compare", [a, b, float(tol)]) is True
    except BaseException:
        return False


def solve_equation(equation: str, variable: str = "x") -> str:
    try:
        return str(_run_isolated("solve", [equation, variable]))
    except BaseException as exc:
        return _error("solve equation", exc)
