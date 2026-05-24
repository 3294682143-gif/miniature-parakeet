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


def test_clean_traces_keeps_gitkeep(tmp_path: Path) -> None:
    traces = tmp_path / "outputs" / "traces"
    traces.mkdir(parents=True)
    (traces / ".gitkeep").write_text("", encoding="utf-8")

    run_regression_gate.clean_traces(tmp_path)

    assert (traces / ".gitkeep").exists()


def test_clean_traces_removes_fake_json(tmp_path: Path) -> None:
    traces = tmp_path / "outputs" / "traces"
    traces.mkdir(parents=True)
    fake = traces / "fake.json"
    fake.write_text("{}", encoding="utf-8")

    run_regression_gate.clean_traces(tmp_path)

    assert not fake.exists()


def test_command_list_contains_required_checks() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=False,
        skip_slow=False,
        no_cli_smoke=False,
    )
    command_lines = {" ".join(cmd) for cmd in commands}

    assert "ruff check ." in command_lines
    assert "black --check src scripts demo tests" in command_lines
    assert "isort --check-only src scripts demo tests" in command_lines
    assert "mypy src --show-error-codes" in command_lines
    assert "pyright" in command_lines
    assert "python -m pytest -q" in command_lines
    assert "python scripts/check_project_safety.py" in command_lines
    assert any("python -m math_agent.cli solve" in line for line in command_lines)


def test_command_list_has_no_real_flag_and_no_dotenv_read() -> None:
    commands = run_regression_gate.build_commands(
        skip_type_checks=False,
        skip_slow=False,
        no_cli_smoke=False,
    )
    flattened = " ".join(" ".join(cmd) for cmd in commands)
    assert "--real" not in flattened
    assert ".env" not in flattened
