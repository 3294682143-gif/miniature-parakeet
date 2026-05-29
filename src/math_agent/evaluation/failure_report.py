from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.evaluation.judge import (
    exact_match,
    normalized_match,
    numeric_match,
    symbolic_match,
)
from math_agent.evaluation.metrics import (
    load_answer_records,
    load_answers,
    load_jsonl,
    proof_evaluation_hit,
    proof_failure_category,
    proof_quality_score,
)
from math_agent.harness.replay import render_replay_markdown, summarize_trace
from math_agent.harness.trace_reader import read_trace
from math_agent.schemas import SolveResult


def classify_failure(
    result: SolveResult,
    gold: str | None,
    evaluation_mode: str = "short_answer",
    answer_row: dict[str, Any] | None = None,
) -> str:
    if result.status == "fail":
        return "status_fail"
    if result.status == "partial":
        return "status_partial"
    if not result.final_answer.value.strip():
        return "missing_final_answer"
    if evaluation_mode in {"proof_validity", "proof_quality"}:
        if proof_evaluation_hit(result, answer_row, evaluation_mode):
            return "pass"
        return proof_failure_category(result, answer_row, evaluation_mode)
    if not result.verification.passed:
        return "verifier_failed"
    if gold is None:
        return "no_gold_answer"
    pred = result.final_answer.value
    if exact_match(pred, gold):
        return "pass"
    if normalized_match(pred, gold):
        return "format_only_exact_mismatch"
    if numeric_match(pred, gold):
        return "normalization_gap_numeric_match"
    if symbolic_match(pred, gold):
        return "normalization_gap_symbolic_match"
    return "answer_mismatch"


def _trace_path(trace_dir: str | Path | None, question_id: str) -> Path | None:
    if not trace_dir:
        return None
    return Path(trace_dir) / f"{question_id}.json"


def build_failure_rows(
    results_path: str | Path,
    answers_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
    include_format_only: bool = True,
) -> list[dict[str, Any]]:
    raw_rows, invalid_count = load_jsonl(results_path)
    answers = load_answers(answers_path)
    answer_records = load_answer_records(answers_path)
    rows: list[dict[str, Any]] = []
    for invalid_index in range(invalid_count):
        rows.append(
            {
                "question_id": f"invalid_json_{invalid_index + 1}",
                "category": "invalid_json",
                "status": "invalid",
                "prediction": "",
                "gold": "",
                "trace_path": "",
                "trace_summary": {},
            }
        )

    for row in raw_rows:
        try:
            result = SolveResult.model_validate(row)
        except Exception:
            rows.append(
                {
                    "question_id": str(row.get("question_id", "unknown")),
                    "category": "schema_invalid",
                    "status": "invalid",
                    "prediction": "",
                    "gold": "",
                    "trace_path": "",
                    "trace_summary": {},
                }
            )
            continue
        gold = answers.get(result.question_id) if answers else None
        answer_row = answer_records.get(result.question_id, {})
        evaluation_mode = str(answer_row.get("evaluation_mode") or "short_answer")
        category = classify_failure(result, gold, evaluation_mode, answer_row)
        if category == "pass":
            continue
        if not include_format_only and category in {
            "format_only_exact_mismatch",
            "normalization_gap_numeric_match",
            "normalization_gap_symbolic_match",
        }:
            continue

        trace_summary: dict[str, Any] = {}
        trace_path = _trace_path(trace_dir, result.question_id)
        if trace_path is not None and trace_path.exists():
            trace_read = read_trace(trace_path)
            if trace_read.get("ok") and isinstance(trace_read.get("trace"), dict):
                trace_summary = summarize_trace(trace_read["trace"])
            else:
                trace_summary = {"trace_error": trace_read.get("error")}

        failure_row = {
            "question_id": result.question_id,
            "category": category,
            "status": result.status,
            "domain": result.domain,
            "problem_type": result.problem_type,
            "prediction": result.final_answer.value,
            "boxed": result.final_answer.boxed,
            "gold": gold or "",
            "evaluation_mode": evaluation_mode,
            "verifier_passed": result.verification.passed,
            "verification_method": result.verification.method,
            "trace_path": str(trace_path or ""),
            "trace_summary": trace_summary,
        }
        if evaluation_mode in {"proof_validity", "proof_quality"}:
            score = proof_quality_score(result)
            failure_row.update(
                {
                    "proof_score": score.score,
                    "proof_complete": score.proof_complete,
                    "proof_partial": score.proof_partial,
                    "proof_invalid": score.proof_invalid,
                    "proof_reasons": score.reasons,
                    "proof_risk_flags": score.risk_flags,
                }
            )
        rows.append(failure_row)
    return rows


def render_failure_report(
    rows: list[dict[str, Any]], title: str = "Failure Replay Report"
) -> str:
    category_counts: dict[str, int] = {}
    for row in rows:
        category = str(row.get("category", "unknown"))
        category_counts[category] = category_counts.get(category, 0) + 1

    lines = [
        f"# {title}",
        "",
        f"- failure_count: {len(rows)}",
        "",
        "## Failure Categories",
        "",
        "| Category | Count |",
        "|---|---:|",
    ]
    for category, count in sorted(category_counts.items()):
        lines.append(f"| {category} | {count} |")

    lines.extend(
        [
            "",
            "## Failure Cases",
            "",
            "| Question ID | Category | Status | Domain | Type | Proof Score | Prediction | Gold | Trace |",
            "|---|---|---|---|---|---:|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| {qid} | {category} | {status} | {domain} | {ptype} | {proof_score} | `{pred}` | `{gold}` | {trace} |".format(
                qid=row.get("question_id", ""),
                category=row.get("category", ""),
                status=row.get("status", ""),
                domain=row.get("domain", ""),
                ptype=row.get("problem_type", ""),
                proof_score=(
                    f"{float(row['proof_score']):.3f}"
                    if isinstance(row.get("proof_score"), (float, int))
                    else ""
                ),
                pred=str(row.get("prediction", "")).replace("|", "\\|")[:120],
                gold=str(row.get("gold", "")).replace("|", "\\|")[:120],
                trace=row.get("trace_path", "") or "missing",
            )
        )

    for row in rows:
        trace_summary = row.get("trace_summary")
        if not isinstance(trace_summary, dict) or not trace_summary:
            continue
        lines.extend(
            [
                "",
                f"## Replay: {row.get('question_id', '')}",
                "",
                render_replay_markdown(trace_summary).strip(),
            ]
        )
    return "\n".join(lines) + "\n"


def write_failure_report(
    results_path: str | Path,
    out_path: str | Path,
    answers_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
    include_format_only: bool = True,
) -> list[dict[str, Any]]:
    rows = build_failure_rows(
        results_path=results_path,
        answers_path=answers_path,
        trace_dir=trace_dir,
        include_format_only=include_format_only,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_failure_report(rows), encoding="utf-8")
    json_out = out.with_suffix(".json")
    json_out.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows
