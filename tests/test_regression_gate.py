from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from scripts import run_regression_gate


def _line(cmd: list[str]) -> str:
    if cmd and cmd[0] == sys.executable:
        return "python " + " ".join(cmd[1:])
    return " ".join(cmd)


def test_script_exists() -> None:
    assert Path("scripts/run_regression_gate.py").is_file()


def test_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_regression_gate.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--include-shadow-eval" in result.stdout


def test_dev_extra_declares_local_gate_tools() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dev_deps = {
        re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip().casefold()
        for requirement in pyproject["project"]["optional-dependencies"]["dev"]
    }
    assert {"ruff", "black", "isort", "mypy", "pyright"}.issubset(dev_deps)


def test_command_list_contains_required_checks() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=False,
        skip_slow=False,
        no_cli_smoke=False,
        include_shadow_eval=False,
    )
    command_lines = {_line(cmd) for cmd in commands}

    assert "python -m ruff check ." in command_lines or "ruff check ." in command_lines
    assert (
        "python -m black --check src scripts demo tests" in command_lines
        or "black --check src scripts demo tests" in command_lines
    )
    assert (
        "python -m isort --check-only --diff src scripts demo tests" in command_lines
        or "isort --check-only --diff src scripts demo tests" in command_lines
    )
    assert (
        "python -m mypy src --show-error-codes" in command_lines
        or "mypy src --show-error-codes" in command_lines
    )
    assert any(
        line == "pyright" or line.startswith("python -m pyright")
        for line in command_lines
    )
    assert "python -m pytest -q" in command_lines
    assert "python scripts/check_project_safety.py" in command_lines
    assert "git status --short" in command_lines
    assert any("python -m math_agent.cli solve" in line for line in command_lines)
    assert any(
        "python -m math_agent.cli solve" in line and "--fail-on-non-success" in line
        for line in command_lines
    )
    lines = [_line(cmd) for cmd in commands]
    compile_idx = lines.index("python -m compileall src scripts demo tests")
    pytest_idx = lines.index("python -m pytest -q")
    cli_idx = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("python -m math_agent.cli solve")
    )
    safety_idx = lines.index("python scripts/check_project_safety.py")
    assert compile_idx < safety_idx
    assert pytest_idx < safety_idx
    assert cli_idx < safety_idx
    assert safety_idx < lines.index("git status --short")


def test_quality_tool_cmd_prefers_current_python_module(monkeypatch) -> None:
    monkeypatch.setattr(
        run_regression_gate.importlib.util,
        "find_spec",
        lambda module: object() if module == "ruff" else None,
    )
    monkeypatch.setattr(run_regression_gate.shutil, "which", lambda _: "ruff.exe")
    assert run_regression_gate.quality_tool_cmd("ruff", "check", ".") == [
        sys.executable,
        "-m",
        "ruff",
        "check",
        ".",
    ]


def test_command_list_has_no_real_flag_and_no_dotenv_read() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=False,
        skip_slow=False,
        no_cli_smoke=False,
        include_shadow_eval=False,
    )
    flattened = " ".join(" ".join(cmd) for cmd in commands)
    assert "--real" not in flattened
    assert ".env" not in flattened


def test_shadow_eval_not_included_by_default() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=False,
        skip_slow=True,
        no_cli_smoke=True,
        include_shadow_eval=False,
    )
    flattened = " ".join(" ".join(cmd) for cmd in commands)
    assert "scripts/shadow_eval.py" not in flattened


def test_shadow_eval_included_when_enabled() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=True,
        skip_slow=True,
        no_cli_smoke=True,
        include_shadow_eval=True,
    )
    lines = [" ".join(cmd) for cmd in commands]
    flattened = " ".join(lines)
    assert any("scripts/shadow_eval.py" in line for line in lines)
    assert "--mock" in flattened
    assert "--limit 5" in flattened
    assert "outputs/shadow_eval_gate" in flattened
    assert any("scripts/build_eval_report.py" in line for line in lines)
    assert "outputs/shadow_eval_gate/shadow_results.jsonl" in flattened
    assert "--real" not in flattened
    assert ".env" not in flattened


def test_run_regression_gate_does_not_use_shell_true() -> None:
    source = Path("scripts/run_regression_gate.py").read_text(encoding="utf-8")
    assert "shell=True" not in source


def test_python_commands_use_current_interpreter() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=True,
        skip_slow=True,
        no_cli_smoke=False,
        include_shadow_eval=True,
    )
    python_commands = [
        cmd
        for cmd in commands
        if cmd[1:2] == ["-m"] or (len(cmd) > 1 and cmd[1].startswith("scripts/"))
    ]
    assert python_commands
    assert all(cmd[0] == sys.executable for cmd in python_commands)


def test_python_commands_prefer_this_checkout_source() -> None:
    env = run_regression_gate.command_env([sys.executable, "-m", "math_agent.cli"])
    assert env is not None
    first = env["PYTHONPATH"].split(run_regression_gate.os.pathsep)[0]
    expected = str(Path("src").resolve())
    assert run_regression_gate.os.path.normcase(
        first
    ) == run_regression_gate.os.path.normcase(expected)


def test_source_checkout_shim_beats_a_stale_editable_install() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import math_agent.cli as m; print(m.__file__)",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert Path(proc.stdout.strip()).resolve().is_relative_to(Path("src").resolve())


def test_missing_quality_tool_has_actionable_message(monkeypatch, capsys) -> None:
    monkeypatch.setattr(run_regression_gate.shutil, "which", lambda _: None)
    try:
        run_regression_gate.run_command(1, 1, ["ruff", "check", "."])
    except SystemExit as exc:
        assert exc.code == 127
    output = capsys.readouterr().out
    assert "Missing local quality tool 'ruff'" in output
    assert "python -m pip install -e .[dev]" in output
