# safety: allow-secret-fixtures
from __future__ import annotations

import json

from math_agent.evaluation.metrics import evaluate_results, render_markdown_report
from math_agent.pipeline import solve_question
from math_agent.schemas import MathQuestion


def _result(
    qid: str,
    status: str,
    domain: str,
    problem_type: str,
    answer: str,
    passed: bool = True,
    confidence: float = 0.8,
    answer_type: str = "text",
    visible_steps: list[str] | None = None,
) -> dict:
    return {
        "question_id": qid,
        "domain": domain,
        "problem_type": problem_type,
        "problem_parse": {"goal": "g", "givens": [], "symbols": []},
        "solution_plan": [],
        "visible_solution_steps": visible_steps or [],
        "tool_trace": [
            {"tool": "none", "purpose": "x", "status": "success", "summary": "ok"}
        ],
        "final_answer": {
            "type": answer_type,
            "value": answer,
            "boxed": "" if answer_type == "proof" else f"\\boxed{{{answer}}}",
        },
        "verification": {"method": "none", "passed": passed, "notes": "n"},
        "didactic_hint": "h",
        "confidence": confidence,
        "status": status,
        "error": None,
    }


def test_empty_file_no_crash(tmp_path):
    p = tmp_path / "results.jsonl"
    p.write_text("", encoding="utf-8")
    m = evaluate_results(p)
    assert m["total"] == 0
    assert m["json_valid_count"] == 0
    assert m["json_valid_rate"] == 0.0
    assert m["result_integrity_ok"] is False


def test_valid_results_stats(tmp_path):
    p = tmp_path / "results.jsonl"
    rows = [
        _result("q1", "success", "Algebra", "equation", "5", True, 0.9),
        _result("q2", "partial", "Geometry", "proof", "2*x", False, 0.6),
        _result("q3", "fail", "Algebra", "equation", "", False, 0.1),
    ]
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    m = evaluate_results(p)
    assert m["total"] == 3
    assert m["json_valid_count"] == 3
    assert m["success_count"] == 1
    assert m["partial_count"] == 1
    assert m["fail_count"] == 1
    assert m["domain_distribution"] == {"Algebra": 2, "Geometry": 1}
    assert m["problem_type_distribution"] == {"equation": 2, "proof": 1}


def test_invalid_json_line_counted(tmp_path):
    p = tmp_path / "results.jsonl"
    ok = json.dumps(
        _result("q1", "success", "Algebra", "equation", "5"), ensure_ascii=False
    )
    p.write_text(ok + "\n{bad json}\n", encoding="utf-8")
    m = evaluate_results(p)
    assert m["total"] == 2
    assert m["json_valid_count"] == 1
    assert m["json_invalid_count"] == 1


def test_answer_matching_metrics(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rows = [
        _result("q1", "success", "Algebra", "equation", "5"),
        _result("q2", "success", "Algebra", "equation", "0.5"),
        _result("q3", "success", "Algebra", "equation", "x+x"),
    ]
    answers = [
        {"question_id": "q1", "answer": "5"},
        {"question_id": "q2", "answer": "1/2"},
        {"question_id": "q3", "answer": "2*x"},
    ]
    rp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    ap.write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in answers) + "\n",
        encoding="utf-8",
    )

    m = evaluate_results(rp, ap)
    assert m["answer_covered_count"] == 3
    assert m["exact_match"] == 1 / 3
    assert m["normalized_match"] >= 1 / 3
    assert m["numeric_match"] >= 1 / 3
    assert m["symbolic_match"] >= 2 / 3


def test_missing_gold_result_uses_strict_gold_denominator(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rp.write_text(
        json.dumps(_result("q1", "success", "algebra", "equation", "5")) + "\n",
        encoding="utf-8",
    )
    answers = [
        {
            "question_id": "q1",
            "answer": "5",
            "domain": "algebra",
            "problem_type": "equation",
        },
        {
            "question_id": "q2",
            "answer": "7",
            "domain": "number_theory",
            "problem_type": "integer",
        },
    ]
    ap.write_text(
        "\n".join(json.dumps(row) for row in answers) + "\n", encoding="utf-8"
    )

    metrics = evaluate_results(rp, ap)

    assert metrics["answer_expected_count"] == 2
    assert metrics["answer_covered_count"] == 1
    assert metrics["answer_missing_count"] == 1
    assert metrics["missing_result_ids"] == ["q2"]
    assert metrics["evaluation_pass_count"] == 1
    assert metrics["evaluation_pass_rate"] == 0.5
    assert metrics["covered_evaluation_pass_rate"] == 1.0
    assert metrics["normalized_match"] == 0.5
    assert metrics["answer_match_by_domain"]["number_theory"]["total"] == 1
    assert (
        metrics["answer_match_by_domain"]["number_theory"]["evaluation_pass_rate"]
        == 0.0
    )


def test_duplicate_and_unexpected_results_never_inflate_score(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rows = [
        _result("q1", "success", "algebra", "equation", "5"),
        _result("q1", "success", "algebra", "equation", "5"),
        _result("extra", "success", "algebra", "equation", "9"),
    ]
    rp.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    ap.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"question_id": "q1", "answer": "5"},
                {"question_id": "q2", "answer": "7"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(rp, ap)

    assert metrics["duplicate_result_ids"] == ["q1"]
    assert metrics["unexpected_result_ids"] == ["extra"]
    assert metrics["answer_covered_count"] == 0
    assert metrics["evaluation_pass_count"] == 0
    assert metrics["evaluation_pass_rate"] == 0.0
    assert metrics["evaluation_integrity_ok"] is False


def test_failed_or_unverified_short_answer_cannot_pass_evaluation(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rp.write_text(
        json.dumps(
            _result(
                "q1",
                "fail",
                "algebra",
                "equation",
                "5",
                passed=False,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    ap.write_text(
        json.dumps({"question_id": "q1", "answer": "5"}) + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(rp, ap)

    assert metrics["normalized_match"] == 0.0
    assert metrics["evaluation_pass_count"] == 0
    assert metrics["evaluation_pass_rate"] == 0.0


def test_duplicate_gold_is_order_independent_and_unscorable(tmp_path):
    rp = tmp_path / "results.jsonl"
    first = tmp_path / "answers_first.jsonl"
    second = tmp_path / "answers_second.jsonl"
    rp.write_text(
        json.dumps(_result("q1", "success", "algebra", "equation", "5")) + "\n",
        encoding="utf-8",
    )
    duplicate_rows = [
        {"question_id": "q1", "answer": "5"},
        {"question_id": "q1", "answer": "6"},
    ]
    first.write_text(
        "\n".join(json.dumps(row) for row in duplicate_rows) + "\n",
        encoding="utf-8",
    )
    second.write_text(
        "\n".join(json.dumps(row) for row in reversed(duplicate_rows)) + "\n",
        encoding="utf-8",
    )

    first_metrics = evaluate_results(rp, first)
    second_metrics = evaluate_results(rp, second)

    for metrics in (first_metrics, second_metrics):
        assert metrics["answer_duplicate_ids"] == ["q1"]
        assert metrics["answer_expected_count"] == 1
        assert metrics["answer_covered_count"] == 0
        assert metrics["evaluation_pass_rate"] == 0.0
        assert metrics["answer_integrity_ok"] is False


def test_invalid_answer_rows_are_reported_without_crashing(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rp.write_text("[]\n", encoding="utf-8")
    ap.write_text('{bad json}\n[]\n{"answer":"5"}\n', encoding="utf-8")

    metrics = evaluate_results(rp, ap)

    assert metrics["json_schema_invalid_count"] == 1
    assert metrics["answer_expected_count"] == 0
    assert metrics["answer_json_invalid_count"] == 1
    assert metrics["answer_schema_invalid_count"] == 1
    assert metrics["answer_invalid_id_count"] == 1
    assert metrics["answer_integrity_ok"] is False
    assert metrics["evaluation_integrity_ok"] is False


def test_missing_or_empty_gold_source_is_never_certified(tmp_path):
    rp = tmp_path / "results.jsonl"
    missing = tmp_path / "missing_answers.jsonl"
    empty = tmp_path / "empty_answers.jsonl"
    rp.write_text("", encoding="utf-8")
    empty.write_text("", encoding="utf-8")

    missing_metrics = evaluate_results(rp, missing)
    empty_metrics = evaluate_results(rp, empty)

    assert missing_metrics["answer_source_exists"] is False
    assert empty_metrics["answer_source_exists"] is True
    for metrics in (missing_metrics, empty_metrics):
        assert metrics["answer_expected_count"] == 0
        assert metrics["answer_integrity_ok"] is False
        assert metrics["evaluation_integrity_ok"] is False


def test_invalid_gold_answer_values_and_modes_are_rejected(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rp.write_text(
        json.dumps(_result("q1", "success", "algebra", "equation", "None")) + "\n",
        encoding="utf-8",
    )
    answer_rows = [
        {"question_id": "q1", "answer": None},
        {"question_id": "q2", "answer": {"value": "5"}},
        {"question_id": "q3"},
        {"question_id": "q4", "answer": "5", "evaluation_mode": "best_of"},
    ]
    ap.write_text(
        "\n".join(json.dumps(row) for row in answer_rows) + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(rp, ap)

    assert metrics["answer_expected_count"] == 0
    assert metrics["answer_schema_invalid_count"] == 4
    assert metrics["answer_integrity_ok"] is False
    assert metrics["evaluation_pass_count"] == 0


def test_answer_matching_grouped_by_answer_metadata(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rows = [
        _result("q1", "success", "Unknown", "unknown", "3x^2 + 2"),
        _result("q2", "success", "Unknown", "unknown", r"\dfrac{3}{8}"),
    ]
    answers = [
        {
            "question_id": "q1",
            "answer": "3*x**2+2",
            "domain": "calculus",
            "problem_type": "derivative",
        },
        {
            "question_id": "q2",
            "answer": "3/8",
            "domain": "probability",
            "problem_type": "binomial",
        },
    ]
    rp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    ap.write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in answers) + "\n",
        encoding="utf-8",
    )
    m = evaluate_results(rp, ap)
    assert m["normalized_match"] == 1.0
    assert m["symbolic_match"] == 1.0
    assert m["answer_match_by_domain"]["calculus"]["normalized_match_rate"] == 1.0
    assert m["answer_match_by_problem_type"]["binomial"]["total"] == 1


def test_trace_budget_metrics_and_markdown_tables(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    row = _result("q1", "success", "Algebra", "equation", "5")
    rp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    ap.write_text(
        json.dumps({"question_id": "q1", "answer": "5"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (trace_dir / "q1.json").write_text(
        json.dumps(
            {
                "question_id": "q1",
                "latency_seconds": 1.25,
                "model_calls": [{"stage": "solver"}, {"stage": "verifier"}],
                "tool_calls": [{"tool": "sympy"}],
                "final_result": row,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    metrics = evaluate_results(rp, ap, trace_dir)
    assert metrics["total_model_calls"] == 2
    assert metrics["total_tool_calls"] == 1
    assert metrics["model_solved_count"] == 1
    assert metrics["model_verified_count"] == 1
    assert metrics["tool_solved_count"] == 0
    assert metrics["tool_override_count"] == 0
    assert metrics["average_latency_seconds"] == 1.25
    report = render_markdown_report(metrics, str(rp), str(ap))
    assert "| Group | Total | Short | Exact |" in report
    assert "## Budget / Trace Metrics" in report
    assert "tool_solved_count" in report


def test_trace_metrics_redact_secret_shaped_directory_on_read_failure(tmp_path):
    rp = tmp_path / "results.jsonl"
    rp.write_text(
        json.dumps(_result("q1", "success", "algebra", "equation", "5")) + "\n",
        encoding="utf-8",
    )
    secret = "xapp-1-ABCDEFGHIJKLMNOP-1234567890-abcdefghijklmnopqrstuv"
    trace_dir = tmp_path / secret

    metrics = evaluate_results(rp, trace_dir=trace_dir)

    assert metrics["trace_read_ok"] is False
    assert metrics["trace_dir"] == "[redacted-path]"
    assert secret not in json.dumps(metrics)


def test_trace_metrics_ignore_unmatched_and_duplicate_question_ids(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    row = _result("q1", "success", "algebra", "equation", "5")
    rp.write_text(json.dumps(row) + "\n", encoding="utf-8")
    ap.write_text(
        json.dumps({"question_id": "q1", "answer": "5"}) + "\n",
        encoding="utf-8",
    )
    base_trace = {
        "latency_seconds": 1.0,
        "model_calls": [{"stage": "solver"}],
        "tool_calls": [{"status": "success", "tool": "sympy"}],
        "final_result": {
            **row,
            "verification": {
                "method": "numeric_check",
                "passed": True,
                "notes": "ok",
            },
        },
    }
    for name, question_id in (("a", "q1"), ("b", "q1"), ("stray", "q2")):
        (trace_dir / f"{name}.json").write_text(
            json.dumps({**base_trace, "question_id": question_id}) + "\n",
            encoding="utf-8",
        )

    metrics = evaluate_results(rp, ap, trace_dir)

    assert metrics["trace_count"] == 0
    assert metrics["trace_duplicate_question_ids"] == ["q1"]
    assert metrics["trace_unmatched_question_ids"] == ["q2"]
    assert metrics["total_model_calls"] == 0
    assert metrics["total_tool_calls"] == 0
    assert metrics["tool_override_count"] == 0


def test_tool_override_requires_explicit_trace_provenance(tmp_path):
    rp = tmp_path / "results.jsonl"
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    row = _result("q1", "success", "algebra", "equation", "5")
    rp.write_text(json.dumps(row) + "\n", encoding="utf-8")
    trace = {
        "question_id": "q1",
        "model_calls": [{"stage": "solver"}],
        "tool_calls": [{"status": "success", "tool": "sympy"}],
        "final_result": {
            **row,
            "verification": {
                "method": "numeric_check",
                "passed": True,
                "notes": "ok",
            },
        },
    }
    trace_path = trace_dir / "q1.json"
    trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")

    verified_metrics = evaluate_results(rp, trace_dir=trace_dir)
    assert verified_metrics["model_then_tool_final_count"] == 1
    assert verified_metrics["tool_override_count"] == 0

    trace_path.write_text(
        json.dumps({**trace, "tool_overrode_model": True}) + "\n",
        encoding="utf-8",
    )
    override_metrics = evaluate_results(rp, trace_dir=trace_dir)
    assert override_metrics["tool_override_count"] == 1


def test_trace_final_result_id_mismatch_is_excluded(tmp_path):
    rp = tmp_path / "results.jsonl"
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    row = _result("q1", "success", "algebra", "equation", "5")
    rp.write_text(json.dumps(row) + "\n", encoding="utf-8")
    (trace_dir / "q1.json").write_text(
        json.dumps(
            {
                "question_id": "q1",
                "model_calls": [{"stage": "solver"}],
                "final_result": {**row, "question_id": "q2"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(rp, trace_dir=trace_dir)

    assert metrics["trace_count"] == 0
    assert metrics["trace_result_question_id_mismatch_count"] == 1
    assert metrics["total_model_calls"] == 0


def test_trace_must_bind_the_complete_result_and_execution_provenance(tmp_path):
    results_path = tmp_path / "results.jsonl"
    answers_path = tmp_path / "answers.jsonl"
    trace_dir = tmp_path / "traces"
    result = solve_question(
        MathQuestion(question_id="bound", question="2+3"),
        mock=True,
        save_trace=True,
        trace_dir=trace_dir,
    )
    results_path.write_text(result.model_dump_json() + "\n", encoding="utf-8")
    answers_path.write_text(
        json.dumps({"question_id": "bound", "answer": "5"}) + "\n",
        encoding="utf-8",
    )
    trace_path = trace_dir / "bound.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["final_result"]["final_answer"]["value"] = "999"
    trace["final_result"]["execution_fingerprint"] = "b" * 64
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    metrics = evaluate_results(results_path, answers_path, trace_dir)

    assert metrics["evaluation_pass_rate"] == 1.0
    assert metrics["trace_count"] == 0
    assert metrics["trace_result_content_mismatch_count"] == 1
    assert metrics["trace_binding_integrity_ok"] is False
    assert metrics["evaluation_integrity_ok"] is False


def test_failed_trace_cannot_count_as_successful_tool_override(tmp_path):
    rp = tmp_path / "results.jsonl"
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    row = _result("q1", "fail", "algebra", "equation", "", passed=False)
    rp.write_text(json.dumps(row) + "\n", encoding="utf-8")
    (trace_dir / "q1.json").write_text(
        json.dumps(
            {
                "question_id": "q1",
                "tool_overrode_model": True,
                "model_calls": [],
                "tool_calls": [],
                "final_result": row,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(rp, trace_dir=trace_dir)

    assert metrics["tool_override_count"] == 0


def test_explanation_quality_metrics(tmp_path):
    rp = tmp_path / "results.jsonl"
    rows = [
        _result(
            "q1",
            "success",
            "Calculus",
            "derivative",
            "3*x**2",
            visible_steps=["Use the power rule, therefore d/dx x^3 = 3*x^2."],
        ),
        _result(
            "q2",
            "success",
            "Algebra",
            "equation",
            "5",
            visible_steps=[],
        ),
    ]
    rows[0]["didactic_hint"] = "The key idea is the derivative power rule."
    rows[1]["didactic_hint"] = "h"
    rp.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    metrics = evaluate_results(rp)
    assert metrics["explanation_checked_count"] == 2
    assert metrics["visible_steps_nonempty_count"] == 1
    assert metrics["didactic_hint_nonempty_count"] == 2
    assert metrics["didactic_hint_template_risk_count"] == 1
    assert metrics["key_idea_coverage_count"] >= 1
    report = render_markdown_report(metrics, str(rp))
    assert "## Explanation Quality" in report


def test_proof_validity_evaluation_mode_is_not_string_matched(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rows = [
        _result(
            "proof_ok",
            "success",
            "proof",
            "proof",
            "Proved: assume the contrary, derive a contradiction, therefore done.",
            True,
            answer_type="proof",
            visible_steps=[
                "Let n be arbitrary. Since the assumption holds, it follows by algebra; therefore the claim is proved."
            ],
        ),
        _result(
            "proof_bad",
            "success",
            "proof",
            "proof",
            "Proved: one-line claim only",
            False,
            answer_type="proof",
            visible_steps=["The claim is obvious."],
        ),
        _result("short_ok", "success", "number_theory", "totient", "24"),
    ]
    answers = [
        {
            "question_id": "proof_ok",
            "answer": "proved",
            "domain": "proof",
            "problem_type": "proof",
            "evaluation_mode": "proof_validity",
        },
        {
            "question_id": "proof_bad",
            "answer": "proved",
            "domain": "proof",
            "problem_type": "proof",
            "evaluation_mode": "proof_validity",
        },
        {
            "question_id": "short_ok",
            "answer": "24",
            "domain": "number_theory",
            "problem_type": "totient",
        },
    ]
    rp.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    ap.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in answers) + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(rp, ap)
    assert metrics["answer_covered_count"] == 2
    assert metrics["json_schema_invalid_count"] == 1
    assert metrics["short_answer_covered_count"] == 1
    assert metrics["proof_validity_covered_count"] == 1
    assert metrics["proof_validity_pass_count"] == 0
    assert metrics["proof_validity_rate"] == 0.0
    assert metrics["proof_quality_average"] > 0
    assert metrics["evaluation_pass_rate"] == 1 / 3
    assert metrics["normalized_match"] == 1.0
    assert metrics["answer_match_by_domain"]["proof"]["total"] == 2
    assert metrics["answer_match_by_domain"]["proof"]["proof_validity_rate"] == 0.0

    report = render_markdown_report(metrics, str(rp), str(ap))
    assert "proof_validity_rate" in report
    assert "Eval Pass Rate" in report


def test_proof_quality_mode_uses_min_score(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    rows = [
        _result(
            "proof_strong",
            "success",
            "proof",
            "proof",
            "Proved.",
            True,
            answer_type="proof",
            visible_steps=[
                "Let n be arbitrary. Since n=2k, then n^2=4k^2, therefore n^2 is even. This proves the claim."
            ],
        ),
        _result(
            "proof_weak",
            "success",
            "proof",
            "proof",
            "Proved.",
            True,
            answer_type="proof",
            visible_steps=["Clearly the result is true."],
        ),
    ]
    answers = [
        {
            "question_id": "proof_strong",
            "answer": "proved",
            "domain": "proof",
            "problem_type": "proof",
            "evaluation_mode": "proof_quality",
            "min_proof_score": 0.68,
        },
        {
            "question_id": "proof_weak",
            "answer": "proved",
            "domain": "proof",
            "problem_type": "proof",
            "evaluation_mode": "proof_quality",
            "min_proof_score": 0.68,
        },
    ]
    rp.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    ap.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in answers) + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(rp, ap)
    assert metrics["proof_validity_covered_count"] == 2
    assert metrics["proof_validity_pass_count"] == 0
    assert metrics["proof_complete_count"] == 1
    assert metrics["proof_partial_count"] == 1
    assert metrics["proof_invalid_count"] == 0
    assert metrics["evaluation_pass_rate"] == 0.0


def test_success_row_with_error_is_schema_invalid_and_never_certified(tmp_path):
    results = tmp_path / "results.jsonl"
    answers = tmp_path / "answers.jsonl"
    row = _result("q1", "success", "algebra", "equation", "5")
    row["error"] = "fatal_backend_error"
    results.write_text(json.dumps(row) + "\n", encoding="utf-8")
    answers.write_text(
        json.dumps({"question_id": "q1", "answer": "5"}) + "\n",
        encoding="utf-8",
    )

    metrics = evaluate_results(results, answers)

    assert metrics["json_schema_invalid_count"] == 1
    assert metrics["evaluation_pass_count"] == 0
    assert metrics["evaluation_integrity_ok"] is False


def test_structurally_complete_false_proof_requires_manual_review(tmp_path):
    rp = tmp_path / "results.jsonl"
    ap = tmp_path / "answers.jsonl"
    row = _result(
        "false_proof",
        "success",
        "proof",
        "proof",
        "Proved.",
        True,
        answer_type="proof",
        visible_steps=[
            "Claim: 1=0. Let n be arbitrary. Since 1+1=2, then 1=0 by theorem X. Therefore 1=0. QED."
        ],
    )
    answer = {
        "question_id": "false_proof",
        "answer": "1 is not equal to 0",
        "evaluation_mode": "proof_quality",
    }
    rp.write_text(json.dumps(row) + "\n", encoding="utf-8")
    ap.write_text(json.dumps(answer) + "\n", encoding="utf-8")

    metrics = evaluate_results(rp, ap)

    assert metrics["proof_validity_pass_count"] == 0
    assert metrics["evaluation_pass_count"] == 0
