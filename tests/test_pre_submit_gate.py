from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.run_pre_submit_gate import build_commands


def test_pre_submit_gate_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/run_pre_submit_gate.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--dry-run-limit" in proc.stdout


def test_pre_submit_gate_command_order() -> None:
    commands = build_commands(
        input_path="data/official_style_18domain_112.jsonl",
        out_dir="outputs/pre_submit_official_style_dry_run",
        dry_run_limit=18,
    )
    rendered = [" ".join(command) for command in commands]
    assert "-m pytest -q" in rendered[0]
    assert "scripts/run_official_dry_run.py" in rendered[1]
    assert "--fail-on-invalid" in rendered[1]
    assert "--fail-on-missing-final" in rendered[1]
    assert rendered[2].endswith("scripts/check_project_safety.py")


def test_pre_submit_gate_source_mentions_cleanup() -> None:
    source = Path("scripts/run_pre_submit_gate.py").read_text(encoding="utf-8")
    assert "clean_transient_artifacts" in source
    assert "official_style_18domain_112.jsonl" in source
