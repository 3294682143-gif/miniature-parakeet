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
    _load_answer_dataset,
    load_jsonl,
    proof_evaluation_hit,
    proof_failure_category,
    proof_quality_score,
)
from math_agent.harness.replay import render_replay_markdown, summarize_trace
from math_agent.harness.trace_reader import read_trace
from math_agent.logging_utils import safe_text_write, trace_path_for_question
from math_agent.schemas import SolveResult, is_semantically_successful
from math_agent.security import redact_sensitive_data


def classify_failure(
    result: SolveResult,
    gold: str | None,
    evaluation_mode: str = "short_answer",
    answer_row: dict[str, Any] | None = None,
) -> str:
    if result.status == "success" and not is_semantically_successful(result):
        return "inconsistent_success_result"
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
    return trace_path_for_question(trace_dir, question_id)


def _failure_fix_category(category: str, proof_flags: list[str]) -> str:
    if category == "status_fail":
        return "retry_or_api_failure"
    if category == "status_partial":
        return "prompt_or_verifier_repair"
    if category == "missing_final_answer":
        return "formatter_repair"
    if category.startswith("proof_") or proof_flags:
        return "proof_prompt_rubric_repair"
    if category in {
        "normalization_gap_numeric_match",
        "normalization_gap_symbolic_match",
        "format_only_exact_mismatch",
    }:
        return "normalizer_or_formatter_repair"
    if category == "verifier_failed":
        return "verifier_repair"
    if category == "answer_mismatch":
        return "solver_prompt_or_tool_routing"
    return "manual_triage"


def _failure_review_bucket(category: str, proof_flags: list[str]) -> str:
    if category == "status_fail":
        return "api_retry_or_runtime_failure"
    if category == "missing_final_answer":
        return "final_answer_format_repair"
    if category.startswith("proof_") or proof_flags:
        return "proof_too_shallow_or_invalid"
    if category in {
        "normalization_gap_numeric_match",
        "normalization_gap_symbolic_match",
        "format_only_exact_mismatch",
    }:
        return "final_answer_format_repair"
    if category == "verifier_failed":
        return "verifier_misjudge_or_threshold"
    if category == "answer_mismatch":
        return "prompt_reasoning_or_tool_routing"
    if category == "status_partial":
        return "prompt_formatter_or_verifier_repair"
    return "manual_review"


def _model_output_preview(result: SolveResult) -> str:
    steps = "\n".join(str(step) for step in result.visible_solution_steps).strip()
    if steps:
        return steps[:800]
    return result.final_answer.value[:800]


def _structural_failure_row(
    question_id: str, category: str, *, gold: str = ""
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question": "",
        "category": category,
        "status": "invalid",
        "domain": "",
        "problem_type": "",
        "model_output_preview": "",
        "prediction": "",
        "gold": gold,
        "trace_path": "",
        "trace_summary": {},
        "proof_risk_flags": [],
        "suggested_fix_category": "evaluation_data_integrity",
        "review_bucket": "evaluation_integrity",
    }


def build_failure_rows(
    results_path: str | Path,
    answers_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
    include_format_only: bool = True,
) -> list[dict[str, Any]]:
    raw_rows, invalid_count = load_jsonl(results_path)
    answer_dataset = _load_answer_dataset(answers_path)
    answers = answer_dataset.answers
    answer_records = answer_dataset.records
    rows: list[dict[str, Any]] = []
    for invalid_index in range(invalid_count):
        rows.append(
            _structural_failure_row(f"invalid_json_{invalid_index + 1}", "invalid_json")
        )

    if answers_path is not None:
        if not answer_dataset.source_exists:
            rows.append(_structural_failure_row("answers", "answer_source_missing"))
        elif not answer_dataset.source_nonempty:
            rows.append(_structural_failure_row("answers", "answer_source_empty"))
        for invalid_index in range(answer_dataset.json_invalid_count):
            rows.append(
                _structural_failure_row(
                    f"answer_invalid_json_{invalid_index + 1}",
                    "answer_invalid_json",
                )
            )
        for invalid_index in range(answer_dataset.schema_invalid_count):
            rows.append(
                _structural_failure_row(
                    f"answer_schema_invalid_{invalid_index + 1}",
                    "answer_schema_invalid",
                )
            )
        for invalid_index in range(answer_dataset.invalid_id_count):
            rows.append(
                _structural_failure_row(
                    f"answer_invalid_question_id_{invalid_index + 1}",
                    "answer_invalid_question_id",
                )
            )
        for question_id in sorted(answer_dataset.duplicate_ids):
            rows.append(
                _structural_failure_row(
                    question_id,
                    "duplicate_answer_id",
                    gold=answers.get(question_id, ""),
                )
            )

    result_groups: dict[str, list[SolveResult]] = {}
    for row_index, row in enumerate(raw_rows, start=1):
        try:
            result = SolveResult.model_validate(row)
        except Exception:
            raw_question_id = row.get("question_id") if isinstance(row, dict) else None
            question_id = (
                raw_question_id.strip()
                if isinstance(raw_question_id, str) and raw_question_id.strip()
                else f"schema_invalid_{row_index}"
            )
            rows.append(_structural_failure_row(question_id, "schema_invalid"))
            continue
        question_id = str(result.question_id).strip()
        if not question_id:
            rows.append(
                _structural_failure_row(
                    f"invalid_question_id_{row_index}", "invalid_question_id"
                )
            )
            continue
        result_groups.setdefault(question_id, []).append(result)

    for question_id, results in sorted(result_groups.items()):
        if len(results) > 1:
            rows.append(_structural_failure_row(question_id, "duplicate_result_id"))

    if answers_path is not None:
        for question_id in sorted(set(answer_records) - set(result_groups)):
            if question_id in answer_dataset.duplicate_ids:
                continue
            rows.append(
                _structural_failure_row(
                    question_id,
                    "missing_result",
                    gold=answers.get(question_id, ""),
                )
            )
        for question_id in sorted(set(result_groups) - set(answer_records)):
            rows.append(_structural_failure_row(question_id, "unexpected_result_id"))

    semantic_results = [
        (question_id, results[0])
        for question_id, results in sorted(result_groups.items())
        if len(results) == 1
        and question_id not in answer_dataset.duplicate_ids
        and (answers_path is None or question_id in answer_records)
    ]
    for question_id, result in semantic_results:
        gold = answers.get(question_id) if answers_path is not None else None
        answer_row = answer_records.get(question_id, {})
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
        question = ""
        trace_path = _trace_path(trace_dir, question_id)
        if trace_path is not None and trace_path.exists():
            trace_read = read_trace(trace_path)
            if trace_read.get("ok") and isinstance(trace_read.get("trace"), dict):
                trace = trace_read["trace"]
                trace_summary = summarize_trace(trace)
                question = str(trace.get("question", ""))
            else:
                trace_summary = {"trace_error": trace_read.get("error")}

        proof_risk_flags: list[str] = []
        proof_score: Any = ""
        proof_complete: Any = ""
        proof_partial: Any = ""
        proof_invalid: Any = ""
        proof_reasons: list[str] = []
        if evaluation_mode in {"proof_validity", "proof_quality"}:
            score = proof_quality_score(result)
            proof_score = score.score
            proof_complete = score.proof_complete
            proof_partial = score.proof_partial
            proof_invalid = score.proof_invalid
            proof_reasons = score.reasons
            proof_risk_flags = score.risk_flags

        failure_row = {
            "question_id": question_id,
            "question": question,
            "category": category,
            "status": result.status,
            "domain": result.domain,
            "problem_type": result.problem_type,
            "model_output_preview": _model_output_preview(result),
            "prediction": result.final_answer.value,
            "final_answer": result.final_answer.model_dump(),
            "boxed": result.final_answer.boxed,
            "gold": gold or "",
            "evaluation_mode": evaluation_mode,
            "verifier_passed": result.verification.passed,
            "verification_method": result.verification.method,
            "verifier_reason": result.verification.notes,
            "proof_risk_flags": proof_risk_flags,
            "suggested_fix_category": _failure_fix_category(category, proof_risk_flags),
            "review_bucket": _failure_review_bucket(category, proof_risk_flags),
            "trace_path": str(trace_path or ""),
            "trace_summary": trace_summary,
        }
        if evaluation_mode in {"proof_validity", "proof_quality"}:
            failure_row.update(
                {
                    "proof_score": proof_score,
                    "proof_complete": proof_complete,
                    "proof_partial": proof_partial,
                    "proof_invalid": proof_invalid,
                    "proof_reasons": proof_reasons,
                }
            )
        sanitized_row = redact_sensitive_data(failure_row)
        rows.append(sanitized_row if isinstance(sanitized_row, dict) else {})
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
        lines.extend(
            [
                "",
                f"## Case: {row.get('question_id', '')}",
                "",
                f"- question: {row.get('question', '') or 'missing'}",
                f"- verifier_reason: {row.get('verifier_reason', '') or 'none'}",
                f"- proof_risk_flags: {', '.join(str(x) for x in row.get('proof_risk_flags', [])) or 'none'}",
                f"- suggested_fix_category: {row.get('suggested_fix_category', 'manual_triage')}",
                f"- review_bucket: {row.get('review_bucket', 'manual_review')}",
                "",
                "```text",
                str(row.get("model_output_preview", "")),
                "```",
            ]
        )
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
    safe_text_write(render_failure_report(rows), out)
    json_out = out.with_suffix(".json")
    safe_text_write(json.dumps(rows, ensure_ascii=False, indent=2), json_out)
    return rows
