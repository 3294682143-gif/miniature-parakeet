from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

from scripts.run_real_api_sample_gate import _is_retryable_failure, _select_question_ids


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
    selected = _select_question_ids(json.loads(json.dumps(rows)), per_domain=2, limit=None)
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


def test_retryable_failure_detects_transient_timeout() -> None:
    result = SimpleNamespace(
        status="fail",
        error="timeout: request timed out",
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
