from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from math_agent.evaluation.failure_report import (
    build_failure_rows,
    write_failure_report,
)


def _result(
    qid: str,
    answer: str,
    status: str = "success",
    answer_type: str = "number",
    verifier_passed: bool = True,
) -> dict:
    return {
        "question_id": qid,
        "domain": "Algebra",
        "problem_type": "calculation",
        "problem_parse": {"goal": "g", "givens": [], "symbols": []},
        "solution_plan": [],
        "visible_solution_steps": [],
        "tool_trace": [],
        "final_answer": {
            "type": answer_type,
            "value": answer,
            "boxed": "" if answer_type == "proof" else f"\\boxed{{{answer}}}",
        },
        "verification": {
            "method": "numeric_check",
            "passed": verifier_passed,
            "notes": "ok",
        },
        "didactic_hint": "h",
        "confidence": 0.8,
        "status": status,
        "error": None,
    }


def test_failure_replay_report_builds_rows_and_files(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    answers = tmp_path / "answers.jsonl"
    traces = tmp_path / "traces"
    traces.mkdir()
    rows = [_result("ok", "5"), _result("bad", "4")]
    results.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    answers.write_text(
        json.dumps({"question_id": "ok", "answer": "5"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"question_id": "bad", "answer": "5"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    (traces / "bad.json").write_text(
        json.dumps(
            {
                "question_id": "bad",
                "question": "2+2",
                "route_info": {"domain": "Algebra", "problem_type": "calculation"},
                "model_calls": [{"stage": "solver"}],
                "tool_calls": [],
                "final_result": rows[1],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    failure_rows = build_failure_rows(results, answers, traces)
    assert [row["question_id"] for row in failure_rows] == ["bad"]
    assert failure_rows[0]["category"] == "answer_mismatch"
    assert failure_rows[0]["question"] == "2+2"
    assert failure_rows[0]["final_answer"]["value"] == "4"
    assert failure_rows[0]["verifier_reason"] == "ok"
    assert failure_rows[0]["suggested_fix_category"] == "solver_prompt_or_tool_routing"
    assert failure_rows[0]["review_bucket"] == "prompt_reasoning_or_tool_routing"

    out = tmp_path / "failure.md"
    write_failure_report(results, out, answers, traces)
    report_text = out.read_text(encoding="utf-8")
    assert "Failure Replay Report" in report_text
    assert "suggested_fix_category" in report_text
    assert "review_bucket" in report_text
    assert out.with_suffix(".json").exists()


def test_failure_replay_script_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/build_failure_replay_report.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--trace-dir" in proc.stdout


def test_failure_replay_can_exclude_normalization_only_rows(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    answers = tmp_path / "answers.jsonl"
    rows = [_result("symbolic_ok", "e^2")]
    results.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    answers.write_text(
        json.dumps(
            {"question_id": "symbolic_ok", "answer": "exp(2)"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    all_rows = build_failure_rows(results, answers)
    hard_rows = build_failure_rows(results, answers, include_format_only=False)
    assert all_rows[0]["category"] == "normalization_gap_symbolic_match"
    assert hard_rows == []


def test_failure_replay_uses_proof_validity_mode(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    answers = tmp_path / "answers.jsonl"
    rows = [
        _result(
            "proof_ok",
            "Proved: assume the contrary and derive a contradiction.",
            answer_type="proof",
        ),
        _result(
            "proof_bad",
            "Proved: assertion only",
            answer_type="proof",
            verifier_passed=False,
        ),
    ]
    answer_rows = [
        {
            "question_id": "proof_ok",
            "answer": "proved",
            "evaluation_mode": "proof_validity",
        },
        {
            "question_id": "proof_bad",
            "answer": "proved",
            "evaluation_mode": "proof_validity",
        },
    ]
    results.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    answers.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in answer_rows) + "\n",
        encoding="utf-8",
    )

    failure_rows = build_failure_rows(results, answers)
    assert [row["question_id"] for row in failure_rows] == ["proof_bad"]
    assert failure_rows[0]["category"] == "proof_verifier_failed"
    assert failure_rows[0]["evaluation_mode"] == "proof_validity"
    assert failure_rows[0]["proof_risk_flags"]
    assert failure_rows[0]["suggested_fix_category"] == "proof_prompt_rubric_repair"
    assert failure_rows[0]["review_bucket"] == "proof_too_shallow_or_invalid"
