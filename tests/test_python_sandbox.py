from math_agent.tools.python_sandbox import run_python_code


def test_basic_math_success() -> None:
    result = run_python_code("print(1+1)")
    assert result["status"] == "success"
    assert "2" in result["stdout"]


def test_infinite_loop_timeout() -> None:
    result = run_python_code("while True:\n    pass", timeout_seconds=1)
    assert result["status"] == "timeout"


def test_import_os_blocked() -> None:
    result = run_python_code("import os\nprint('x')")
    assert result["status"] == "blocked"


def test_open_blocked() -> None:
    result = run_python_code("open('x.txt', 'w')")
    assert result["status"] == "blocked"


def test_requests_blocked() -> None:
    result = run_python_code("import requests")
    assert result["status"] == "blocked"


def test_sympy_works() -> None:
    result = run_python_code("from sympy import symbols\nx=symbols('x')\nprint((x+x).expand())")
    assert result["status"] == "success"
    assert "2*x" in result["stdout"]
