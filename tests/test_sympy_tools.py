import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import math_agent.tools.safe_sympy as safe_sympy_module
import math_agent.tools.sympy_tools as sympy_module
from math_agent.tools.safe_sympy import (
    UnsafeMathExpressionError,
    parse_math_expression,
)
from math_agent.tools.sympy_tools import (
    check_equivalent,
    choose,
    differentiate_expression,
    integrate_expression,
    limit_expression,
    numeric_compare,
    simplify_expression,
    solve_equation,
)


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


def test_deterministic_calculus_and_combinatorics_tools() -> None:
    assert differentiate_expression("sin(x)") == "cos(x)"
    assert limit_expression("x**2 + 3*x", "x", "2") == "10"
    assert integrate_expression("2*x", "x", "0", "3") == "9"
    assert choose(12, 2) == "66"


def test_untrusted_python_syntax_is_rejected() -> None:
    payload = "len([1, 2])"

    assert simplify_expression(payload).startswith("ERROR:")
    assert check_equivalent(payload, "2") is False
    assert numeric_compare(payload, "2") is False


def test_attribute_access_is_rejected() -> None:
    assert simplify_expression("Symbol.__class__").startswith("ERROR:")


def test_excessive_numeric_exponent_is_rejected() -> None:
    assert simplify_expression("2**1000000").startswith("ERROR:")


def test_complex_numeric_exponent_cannot_bypass_the_bound() -> None:
    assert simplify_expression("2**(10000+I)").startswith("ERROR:")
    assert simplify_expression("2**(800+800*I)").startswith("ERROR:")


def test_symbolic_cancellation_cannot_bypass_the_exponent_bound() -> None:
    bypasses = [
        "2**(1001+x-x)",
        "2**(999+2+x-x)",
        "2**(500*3+x-x)",
        "2**(500+501+x+y-y-x)",
        "2**((x+1)-(x-1000))",
    ]

    for expression in bypasses:
        assert simplify_expression(expression).startswith("ERROR:")


def test_nested_symbolic_cancellation_cannot_bypass_the_exponent_bound() -> None:
    bypasses = [
        "2**((999+2+x-x)**1)",
        "2**(Abs(999+2+x-x))",
    ]

    for expression in bypasses:
        assert simplify_expression(expression).startswith("ERROR:")


def test_symbolic_cancellation_keeps_the_exponent_boundary_valid() -> None:
    assert simplify_expression("2**(1000+x-x)") == str(2**1000)


def test_exponent_validation_does_not_call_general_simplify(monkeypatch) -> None:
    def reject_general_simplify(*args, **kwargs):
        raise AssertionError("general simplify is not allowed during validation")

    for function_name in ("cancel", "expand", "factor", "simplify"):
        monkeypatch.setattr(
            safe_sympy_module.sp, function_name, reject_general_simplify
        )

    parsed = parse_math_expression("2**(1000+x-x)")

    assert isinstance(parsed, safe_sympy_module.sp.Pow)
    assert parsed.exp.is_number is False


def test_exponent_normalization_budget_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(safe_sympy_module, "MAX_EXPONENT_VALIDATION_OPERATIONS", 2)

    with pytest.raises(UnsafeMathExpressionError, match="normalization is too complex"):
        parse_math_expression("2**(x-x+1)")


def test_safe_parser_keeps_common_math_notation() -> None:
    assert check_equivalent("2x", "x+x") is True
    assert numeric_compare("1e-3", "0.001") is True


def test_safe_parser_rejects_python_language_features() -> None:
    unsupported = [
        "__import__('os')",
        "open('file')",
        "sin.__class__",
        "x[0]",
        "lambda x: x",
        "1; 2",
        "globals()",
        "eval(1)",
        "Symbol('x')",
        "f(x)",
    ]

    for expression in unsupported:
        assert simplify_expression(expression).startswith("ERROR:")


def test_safe_parser_rejects_oversized_inputs() -> None:
    assert simplify_expression("9" * 65).startswith("ERROR:")
    assert simplify_expression("1e1000000").startswith("ERROR:")
    assert simplify_expression("x+" * 300 + "x").startswith("ERROR:")


def test_choose_rejects_resource_exhausting_combinations() -> None:
    started = time.perf_counter()
    result = choose(1_000_000_000, 500_000_000)

    assert result.startswith("ERROR:")
    assert time.perf_counter() - started < 1.0


def test_sympy_algorithmic_complexity_is_bounded() -> None:
    expression = "sin(" * 80 + "x" + ")" * 80
    started = time.perf_counter()
    result = integrate_expression(expression)

    assert result.startswith("ERROR:")
    assert time.perf_counter() - started < 5.0


def test_duplicate_sympy_worker_response_keys_fail_closed(monkeypatch) -> None:
    class Process:
        pid = 123
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return b'{"ok":true,"value":"1","value":"999"}', b""

        def poll(self):
            return 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    class Job:
        def close(self):
            return None

    monkeypatch.setattr(
        sympy_module.subprocess, "Popen", lambda *args, **kwargs: Process()
    )
    monkeypatch.setattr(
        sympy_module, "assign_windows_job_limits", lambda *args, **kwargs: Job()
    )

    assert simplify_expression("1").startswith("ERROR:")


def test_sympy_worker_rejects_duplicate_request_keys() -> None:
    worker = Path(sympy_module.__file__).with_name("sympy_worker.py")
    completed = subprocess.run(
        [sys.executable, "-E", str(worker)],
        input=b'{"operation":"simplify","operation":"equivalent","arguments":["1","1"]}',
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"ok": False, "error": "operation rejected"}
