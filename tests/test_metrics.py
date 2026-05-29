from __future__ import annotations

import json

from math_agent.evaluation.metrics import evaluate_results, render_markdown_report


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
    assert metrics["answer_covered_count"] == 3
    assert metrics["short_answer_covered_count"] == 1
    assert metrics["proof_validity_covered_count"] == 2
    assert metrics["proof_validity_pass_count"] == 1
    assert metrics["proof_validity_rate"] == 0.5
    assert metrics["proof_quality_average"] > 0
    assert metrics["evaluation_pass_rate"] == 2 / 3
    assert metrics["normalized_match"] == 1.0
    assert metrics["answer_match_by_domain"]["proof"]["total"] == 2
    assert metrics["answer_match_by_domain"]["proof"]["proof_validity_rate"] == 0.5

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
    assert metrics["proof_validity_pass_count"] == 1
    assert metrics["proof_complete_count"] == 1
    assert metrics["proof_partial_count"] == 1
    assert metrics["proof_invalid_count"] == 0
    assert metrics["evaluation_pass_rate"] == 0.5
