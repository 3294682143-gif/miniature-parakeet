from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

from scripts.run_real_api_sample_gate import (
    _build_domain_dashboard,
    _failure_question_ids_from_report,
    _is_retryable_failure,
    _render_domain_dashboard,
    _run_real_preflight,
    _select_question_ids,
)


def test_real_api_sample_gate_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/run_real_api_sample_gate.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--allow-real" in proc.stdout
    assert "--per-domain" in proc.stdout
    assert "--include-proof" in proc.stdout
    assert "--max-attempts" in proc.stdout
    assert "--rerun-failures-from" in proc.stdout
    assert "--skip-preflight" in proc.stdout


def test_real_api_sample_gate_refuses_without_explicit_real() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/run_real_api_sample_gate.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "--real --allow-real" in proc.stderr


def test_select_question_ids_balances_by_domain() -> None:
    rows = [
        {"question_id": "a1", "domain": "A"},
        {"question_id": "a2", "domain": "A"},
        {"question_id": "a3", "domain": "A"},
        {"question_id": "b1", "domain": "B"},
        {"question_id": "b2", "domain": "B"},
    ]
    selected = _select_question_ids(
        json.loads(json.dumps(rows)),
        per_domain=2,
        limit=None,
    )
    assert selected == {"a1", "a2", "b1", "b2"}


def test_select_question_ids_can_include_one_proof_per_domain() -> None:
    rows = [
        {"question_id": "a1", "domain": "A", "evaluation_mode": "short_answer"},
        {"question_id": "a2", "domain": "A", "evaluation_mode": "short_answer"},
        {"question_id": "ap", "domain": "A", "evaluation_mode": "proof_quality"},
        {"question_id": "b1", "domain": "B", "evaluation_mode": "short_answer"},
        {"question_id": "bp", "domain": "B", "problem_type": "proof"},
    ]
    selected = _select_question_ids(
        json.loads(json.dumps(rows)),
        per_domain=1,
        limit=None,
        include_proof=True,
    )
    assert selected == {"a1", "ap", "b1", "bp"}


def test_failure_question_ids_from_report_json_and_markdown(tmp_path) -> None:
    json_report = tmp_path / "failure_replay_report.json"
    json_report.write_text(
        json.dumps(
            [{"question_id": "q1"}, {"question_id": "q2"}, {"ignored": True}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert _failure_question_ids_from_report(json_report) == {"q1", "q2"}

    md_report = tmp_path / "failure_replay_report.md"
    md_report.write_text(
        "# Failure Replay Report\n\n## Case: q3\n\n## Case: q4\n",
        encoding="utf-8",
    )
    assert _failure_question_ids_from_report(md_report) == {"q3", "q4"}


def test_retryable_failure_detects_transient_timeout() -> None:
    result = SimpleNamespace(
        status="fail",
        error="timeout: request timed out",
        verification=SimpleNamespace(notes=""),
    )
    assert _is_retryable_failure(result)


def test_retryable_failure_detects_network_error() -> None:
    result = SimpleNamespace(
        status="fail",
        error="unknown_error: network request failed",
        verification=SimpleNamespace(notes=""),
    )
    assert _is_retryable_failure(result)


def test_retryable_failure_ignores_non_fail_results() -> None:
    result = SimpleNamespace(
        status="partial",
        error="timeout: request timed out",
        verification=SimpleNamespace(notes=""),
    )
    assert not _is_retryable_failure(result)


def test_real_preflight_success() -> None:
    class Client:
        def chat(self, **kwargs):
            return "OK"

    assert _run_real_preflight(Client()) == (True, "ok")


def test_real_preflight_failure_is_sanitized() -> None:
    class Client:
        def chat(self, **kwargs):
            raise ValueError("unknown_error: network request failed")

    ok, message = _run_real_preflight(Client())
    assert not ok
    assert message == "unknown_error: network request failed"


def test_domain_dashboard_exposes_hard_gate_fields(tmp_path) -> None:
    traces = tmp_path / "traces"
    traces.mkdir()
    (traces / "alg_1.json").write_text(
        json.dumps(
            {
                "model_calls": [{"stage": "solver"}],
                "tool_calls": [{"tool": "sympy"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result_rows = [
        {
            "question_id": "alg_1",
            "domain": "Algebra",
            "status": "success",
            "verification": {"passed": True},
        },
        {
            "question_id": "alg_2",
            "domain": "Algebra",
            "status": "partial",
            "verification": {"passed": False},
        },
    ]
    answer_rows = [
        {"question_id": "alg_1", "domain": "Algebra"},
        {"question_id": "alg_2", "domain": "Algebra"},
    ]
    dashboard = _build_domain_dashboard(
        result_rows=result_rows,
        answer_rows=answer_rows,
        trace_dir=traces,
        proof_rows=[{"question_id": "alg_2", "risk_flags": ["proof_partial"]}],
        failure_rows=[{"question_id": "alg_2"}],
    )
    assert dashboard == [
        {
            "domain": "Algebra",
            "sample_count": 2,
            "pass_count": 1,
            "partial_count": 1,
            "fail_count": 0,
            "real_sample_pass_rate": 0.5,
            "proof_risk_count": 1,
            "model_calls": 1,
            "tool_calls": 1,
            "tool_solved_count": 1,
            "model_solved_count": 1,
            "model_verified_count": 1,
            "failure_question_ids": ["alg_2"],
            "failure_replay_links": ["failure_replay_report.md#case-alg-2"],
        }
    ]
    rendered = _render_domain_dashboard(dashboard)
    assert "Real API Sample Domain Dashboard" in rendered
    assert "Tool Solved" in rendered
