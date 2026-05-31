from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.build_final_submission_report import (
    _gate_environment_status,
    _real_api_status,
    render_final_submission_report,
)


def test_real_api_status_classification() -> None:
    assert _real_api_status({}) == "missing"
    assert _real_api_status({"total_model_calls": 0}) == "blocked_or_not_executed"
    assert _real_api_status({"total_model_calls": 2, "fail_count": 1}) == (
        "needs_failure_closure"
    )
    assert _real_api_status({"total_model_calls": 2, "fail_count": 0}) == "passed"


def test_gate_environment_status_classification() -> None:
    assert _gate_environment_status({}) == "missing"
    assert _gate_environment_status({"ready_for_regression_gate": False}) == (
        "needs_setup"
    )
    assert (
        _gate_environment_status(
            {
                "ready_for_regression_gate": True,
                "ready_for_real_api_env": True,
                "ready_for_real_api_gate": False,
            }
        )
        == "needs_real_api_preflight"
    )
    assert (
        _gate_environment_status(
            {
                "ready_for_regression_gate": True,
                "ready_for_real_api_gate": True,
            }
        )
        == "ready"
    )


def test_render_final_submission_report_contains_core_evidence() -> None:
    text = render_final_submission_report(
        real_api_summary={
            "preflight": "passed",
            "sample_count": 2,
            "domain_count": 1,
            "pass_count": 1,
            "partial_count": 0,
            "fail_count": 1,
            "total_model_calls": 2,
            "total_tool_calls": 1,
            "model_verified_count": 1,
        },
        domain_dashboard=[
            {
                "domain": "Algebra",
                "sample_count": 2,
                "pass_count": 1,
                "partial_count": 0,
                "fail_count": 1,
                "proof_risk_count": 1,
                "model_calls": 2,
                "tool_calls": 1,
                "failure_question_ids": ["alg_2"],
            }
        ],
        failure_rows=[{"review_bucket": "proof_too_shallow_or_invalid"}],
        gate_environment={
            "ready_for_regression_gate": False,
            "ready_for_real_api_env": True,
            "ready_for_real_api_gate": False,
            "missing_dev_tools": ["ruff"],
            "real_api": {
                "has_api_key": True,
                "has_base_url": True,
                "preflight": "skipped",
            },
        },
    )
    assert "Final Submission Evidence Report" in text
    assert "This is NOT official evaluation" in text
    assert "total_model_calls" in text
    assert "Algebra" in text
    assert "proof_too_shallow_or_invalid" in text
    assert "lagent Alignment Evidence" in text
    assert "Gate Environment Readiness" in text
    assert "Final Reviewer Evidence" in text
    assert "Failure closure table" in text
    assert "missing_dev_tools" in text
    assert "ruff" in text


def test_cli_writes_report_from_local_summaries(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    dashboard = tmp_path / "dashboard.json"
    failures = tmp_path / "failures.json"
    gate_env = tmp_path / "gate_env.json"
    out_dir = tmp_path / "out"
    summary.write_text(
        json.dumps(
            {
                "preflight": "passed",
                "sample_count": 1,
                "domain_count": 1,
                "pass_count": 1,
                "fail_count": 0,
                "total_model_calls": 1,
            }
        ),
        encoding="utf-8",
    )
    dashboard.write_text(
        json.dumps(
            [
                {
                    "domain": "PDE",
                    "sample_count": 1,
                    "pass_count": 1,
                    "partial_count": 0,
                    "fail_count": 0,
                    "proof_risk_count": 0,
                    "model_calls": 1,
                    "tool_calls": 0,
                    "failure_question_ids": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    failures.write_text("[]", encoding="utf-8")
    gate_env.write_text(
        json.dumps(
            {
                "ready_for_regression_gate": True,
                "ready_for_real_api_env": True,
                "ready_for_real_api_gate": True,
                "missing_dev_tools": [],
                "real_api": {"preflight": "passed"},
            }
        ),
        encoding="utf-8",
    )

    run = subprocess.run(
        [
            sys.executable,
            "scripts/build_final_submission_report.py",
            "--real-api-summary",
            str(summary),
            "--domain-dashboard",
            str(dashboard),
            "--failure-report",
            str(failures),
            "--gate-environment",
            str(gate_env),
            "--out-dir",
            str(out_dir),
            "--fail-on-missing-real-api",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert "real_api_status=passed" in run.stdout
    report = (out_dir / "final_submission_report.md").read_text(encoding="utf-8")
    assert "PDE" in report
    assert "Quality gate evidence" in report
    assert not (out_dir / "official_results.jsonl").exists()


def test_cli_can_fail_on_missing_real_api(tmp_path: Path) -> None:
    run = subprocess.run(
        [
            sys.executable,
            "scripts/build_final_submission_report.py",
            "--out-dir",
            str(tmp_path / "out"),
            "--real-api-summary",
            str(tmp_path / "missing.json"),
            "--fail-on-missing-real-api",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 4
    assert "real_api_status=missing" in run.stdout
