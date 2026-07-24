import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import math_agent.tools.python_sandbox as sandbox_module
from math_agent.tools.python_sandbox import (
    SandboxPolicyError,
    evaluate_arithmetic_expression,
    run_python_code,
)


def test_basic_math_success() -> None:
    result = run_python_code("print(1+1)")
    assert result["status"] == "success"
    assert "2" in result["stdout"]


def test_in_process_arithmetic_expression_uses_resource_limits() -> None:
    assert evaluate_arithmetic_expression("(2 + 3) * 4") == 20
    with pytest.raises(SandboxPolicyError):
        evaluate_arithmetic_expression("9**1000000000")
    with pytest.raises(SandboxPolicyError):
        evaluate_arithmetic_expression("+".join("1" for _ in range(300)))


def test_infinite_loop_is_blocked_before_execution() -> None:
    result = run_python_code("while True:\n    pass", timeout_seconds=1)
    assert result["status"] == "blocked"


def test_import_os_blocked() -> None:
    result = run_python_code("import os\nprint('x')")
    assert result["status"] == "blocked"


def test_open_blocked() -> None:
    result = run_python_code("open('x.txt', 'w')")
    assert result["status"] == "blocked"


def test_requests_blocked() -> None:
    result = run_python_code("import requests")
    assert result["status"] == "blocked"


def test_sympy_import_is_blocked() -> None:
    result = run_python_code(
        "from sympy import symbols\nx=symbols('x')\nprint((x+x).expand())"
    )
    assert result["status"] == "blocked"


def test_indirect_module_access_is_blocked() -> None:
    result = run_python_code(
        "import fractions\nprint(fractions.sys.version_info.major)"
    )
    assert result["status"] == "blocked"


def test_builtin_attribute_recovery_is_blocked() -> None:
    result = run_python_code("print(print.__self__.__dict__['len']([1]))")
    assert result["status"] == "blocked"


def test_assignment_and_safe_arithmetic_still_work() -> None:
    result = run_python_code("x = 3\ny = 4\nprint(x**2 + y)")
    assert result["status"] == "success"
    assert result["stdout"] == "13\n"


def test_unknown_function_call_is_blocked() -> None:
    result = run_python_code("globals()")
    assert result["status"] == "blocked"


def test_excessive_power_is_blocked() -> None:
    result = run_python_code("print(2**10001)")
    assert result["status"] == "blocked"


def test_excessive_output_is_blocked() -> None:
    result = run_python_code("print('x' * 100000)")
    assert result["status"] == "blocked"


def test_object_graph_and_dynamic_syntax_are_blocked() -> None:
    unsupported = [
        "print((1).__class__)",
        "x = [1]\nprint(x[0])",
        "print([x for x in [1]])",
        "print(f'{1}')",
        "print(*[1])",
        "print(value=1)",
        "print({'x': 1})",
        "_private = 1",
        "print = 1",
    ]

    for code in unsupported:
        assert run_python_code(code)["status"] == "blocked"


def test_numeric_and_parser_resource_limits_are_blocked() -> None:
    huge_integer = "9" * 1_500
    deeply_nested = "(" * 1_000 + "1" + ")" * 1_000

    assert run_python_code(huge_integer)["status"] == "blocked"
    assert run_python_code(deeply_nested)["status"] == "blocked"
    assert run_python_code("print(1e309)")["status"] == "blocked"


def test_timeout_parameter_is_bounded() -> None:
    assert run_python_code("print(1)", timeout_seconds=0)["status"] == "blocked"
    assert run_python_code("print(1)", timeout_seconds=31)["status"] == "blocked"
    assert run_python_code("print(1)", timeout_seconds=True)["status"] == "blocked"


def test_safe_collection_helpers_work() -> None:
    result = run_python_code("values = [1, 2, 3]\nprint(sum(values), max(values))")

    assert result["status"] == "success"
    assert result["stdout"] == "6 3\n"


def test_output_near_limit_returns_without_queue_deadlock() -> None:
    result = run_python_code("print('x' * 8000)", timeout_seconds=2)

    assert result["status"] == "success"
    assert len(result["stdout"]) == 8001


def test_nested_values_are_blocked_before_unbounded_rendering() -> None:
    result = run_python_code("s = 'x' * 8000\nx = [s] * 16\ny = [x] * 16\nprint(y)")

    assert result["status"] == "blocked"


def test_worker_does_not_replay_python_dash_c_entrypoint() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_root = str(repository_root / "src")
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        os.pathsep.join((source_root, existing_python_path))
        if existing_python_path
        else source_root
    )
    command = (
        "import json; "
        "from math_agent.tools.python_sandbox import run_python_code; "
        "print(json.dumps(run_python_code('print(6 * 7)')))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "success"
    assert result["stdout"] == "42\n"


def test_worker_does_not_replay_python_stdin_entrypoint() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    source_root = str(repository_root / "src")
    environment["PYTHONPATH"] = source_root
    caller = (
        "import json\n"
        "from math_agent.tools.python_sandbox import run_python_code\n"
        "print(json.dumps(run_python_code('print(7 * 8)')))\n"
    )

    completed = subprocess.run(
        [sys.executable, "-"],
        cwd=repository_root,
        env=environment,
        input=caller,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "success"
    assert result["stdout"] == "56\n"


def test_unpaired_unicode_surrogate_is_blocked() -> None:
    result = run_python_code("print('\\ud800')")

    assert result["status"] == "blocked"


def test_duplicate_worker_response_keys_fail_closed(monkeypatch) -> None:
    response = subprocess.CompletedProcess(
        args=["worker"],
        returncode=0,
        stdout=(
            '{"status":"success","status":"blocked","stdout":"",'
            '"stderr":"","result_summary":"forged"}'
        ),
        stderr="",
    )
    monkeypatch.setattr(
        sandbox_module.subprocess, "run", lambda *args, **kwargs: response
    )

    result = run_python_code("print(1)")

    assert result["status"] == "error"
    assert result["result_summary"] == "Sandbox execution failed."
