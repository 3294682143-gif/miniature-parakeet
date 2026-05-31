from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import check_gate_environment as gate_env


def test_report_does_not_include_secret_values(monkeypatch) -> None:
    secret = "super-secret-key"
    monkeypatch.setenv("INTERNS1_API_KEY", secret)
    monkeypatch.setenv("INTERNS1_BASE_URL", "https://example.com")
    report = gate_env.build_environment_report(run_preflight=False)
    text = gate_env.render_markdown(report)
    assert secret not in json.dumps(report)
    assert secret not in text
    assert "has_api_key: True" in text
    assert report["ready_for_real_api_env"] is True
    assert report["ready_for_real_api_gate"] is False


def test_inspect_dev_tools_reports_missing_without_crash(monkeypatch) -> None:
    monkeypatch.setattr(gate_env.importlib.util, "find_spec", lambda _: None)
    monkeypatch.setattr(gate_env.shutil, "which", lambda _: None)
    report = gate_env.build_environment_report(run_preflight=False)
    assert set(report["missing_dev_tools"]) == set(gate_env.DEV_TOOLS)
    assert report["ready_for_regression_gate"] is False


def test_cli_writes_reports(tmp_path: Path) -> None:
    out = tmp_path / "gate_env"
    run = subprocess.run(
        [
            sys.executable,
            "scripts/check_gate_environment.py",
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert "ready_for_regression_gate=" in run.stdout
    assert (out / "gate_environment_report.md").exists()
    assert (out / "gate_environment_report.json").exists()


def test_cli_refuses_real_without_allow_real(tmp_path: Path) -> None:
    run = subprocess.run(
        [
            sys.executable,
            "scripts/check_gate_environment.py",
            "--out-dir",
            str(tmp_path / "gate_env"),
            "--real",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 2
    assert "--real --allow-real" in run.stderr
