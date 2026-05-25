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
    assert any("python -m math_agent.cli solve" in line for line in command_lines)


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


def test_clean_shadow_eval_outputs(tmp_path: Path) -> None:
    gate_dir = tmp_path / "outputs" / "shadow_eval_gate"
    test_dir = tmp_path / "outputs" / "shadow_eval_test"
    gate_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (gate_dir / "tmp.txt").write_text("x", encoding="utf-8")
    (test_dir / "tmp.txt").write_text("x", encoding="utf-8")
    run_regression_gate.clean_shadow_eval_outputs(tmp_path)
    assert not gate_dir.exists()
    assert not test_dir.exists()


def test_run_regression_gate_does_not_use_shell_true() -> None:
    source = Path("scripts/run_regression_gate.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
