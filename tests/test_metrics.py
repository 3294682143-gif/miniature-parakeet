from __future__ import annotations

import json

from math_agent.evaluation.metrics import evaluate_results


def _result(qid: str, status: str, domain: str, problem_type: str, answer: str, passed: bool = True, confidence: float = 0.8) -> dict:
    return {
        "question_id": qid,
        "domain": domain,
        "problem_type": problem_type,
        "problem_parse": {"goal": "g", "givens": [], "symbols": []},
        "solution_plan": [],
        "visible_solution_steps": [],
        "tool_trace": [{"tool": "none", "purpose": "x", "status": "success", "summary": "ok"}],
        "final_answer": {"type": "text", "value": answer, "boxed": f"\\boxed{{{answer}}}"},
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
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
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
    ok = json.dumps(_result("q1", "success", "Algebra", "equation", "5"), ensure_ascii=False)
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
    rp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    ap.write_text("\n".join(json.dumps(a, ensure_ascii=False) for a in answers) + "\n", encoding="utf-8")

    m = evaluate_results(rp, ap)
    assert m["answer_covered_count"] == 3
    assert m["exact_match"] == 1 / 3
    assert m["normalized_match"] >= 1 / 3
    assert m["numeric_match"] >= 1 / 3
    assert m["symbolic_match"] >= 2 / 3
