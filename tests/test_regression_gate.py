from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import run_regression_gate


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


def test_command_list_contains_required_checks() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=False,
        skip_slow=False,
        no_cli_smoke=False,
        include_shadow_eval=False,
    )
    command_lines = {" ".join(cmd) for cmd in commands}

    assert "ruff check ." in command_lines
    assert "black --check src scripts demo tests" in command_lines
    assert "isort --check-only --diff src scripts demo tests" in command_lines
    assert "mypy src --show-error-codes" in command_lines
    assert "pyright" in command_lines
    assert "python -m pytest -q" in command_lines
    assert "python scripts/check_project_safety.py" in command_lines
    assert "git status --short" in command_lines
    assert any("python -m math_agent.cli solve" in line for line in command_lines)
    lines = [" ".join(cmd) for cmd in commands]
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
