from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.evaluation.metrics import (
    load_answer_records,
    load_jsonl,
    proof_quality_score,
)
from math_agent.harness.trace_reader import read_trace
from math_agent.logging_utils import safe_text_write, trace_path_for_question
from math_agent.schemas import SolveResult
from math_agent.security import redact_sensitive_data

RISK_FEEDBACK = {
    "proof_partial": "Add missing assumptions, intermediate lemmas, and an explicit final conclusion.",
    "proof_invalid": "Reject or regenerate; the proof fails the structural validity rubric.",
    "proof_empty": "Regenerate with a non-empty proof body before final formatting.",
    "proof_shallow_assertion": "Replace obvious/trivial assertions with theorem-backed steps.",
    "proof_contradiction_risk": "Clarify the contradiction assumption and derive the contradiction explicitly.",
    "proof_circular_reasoning_risk": "Remove circular dependence on the target conclusion.",
}
MANUAL_SEMANTIC_REVIEW_MESSAGE = (
    "Verify that every inference proves the exact stated claim; structural rubric "
    "scores are not semantic approval."
)


def _trace_path(trace_dir: str | Path | None, question_id: str) -> Path | None:
    if not trace_dir:
        return None
    return trace_path_for_question(trace_dir, question_id)


def _read_question_from_trace(trace_path: Path | None) -> str:
    if trace_path is None or not trace_path.exists():
        return ""
    trace_read = read_trace(trace_path)
    if not trace_read.get("ok") or not isinstance(trace_read.get("trace"), dict):
        return ""
    return str(trace_read["trace"].get("question", ""))


def _proof_text(result: SolveResult) -> str:
    steps = "\n".join(str(step) for step in result.visible_solution_steps)
    final_value = result.final_answer.value.strip()
    if steps.strip() and final_value:
        return f"{steps}\n{final_value}"
    return steps.strip() or final_value


def proof_review_feedback(risk_flags: list[str], reasons: list[str]) -> list[str]:
    feedback: list[str] = [MANUAL_SEMANTIC_REVIEW_MESSAGE]
    for flag in risk_flags:
        item = RISK_FEEDBACK.get(str(flag))
        if item:
            feedback.append(item)
    if "proof_partial_structure" in reasons and not any(
        "intermediate lemmas" in item for item in feedback
    ):
        feedback.append(
            "Strengthen the reasoning chain before accepting the proof as complete."
        )
    return list(dict.fromkeys(feedback))


def build_proof_review_rows(
    results_path: str | Path,
    answers_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    raw_rows, _ = load_jsonl(results_path)
    answer_records = load_answer_records(answers_path)
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        try:
            result = SolveResult.model_validate(raw)
        except Exception:
            continue
        answer_row = answer_records.get(result.question_id, {})
        evaluation_mode = str(answer_row.get("evaluation_mode") or "short_answer")
        if evaluation_mode not in {"proof_validity", "proof_quality"} and (
            result.final_answer.type != "proof"
        ):
            continue
        score = proof_quality_score(result)
        trace_path = _trace_path(trace_dir, result.question_id)
        row = redact_sensitive_data(
            {
                "question_id": result.question_id,
                "question": _read_question_from_trace(trace_path),
                "domain": str(answer_row.get("domain") or result.domain),
                "problem_type": str(
                    answer_row.get("problem_type") or result.problem_type
                ),
                "evaluation_mode": evaluation_mode,
                "status": result.status,
                "verifier_passed": result.verification.passed,
                "verification_method": result.verification.method,
                "proof_score": score.score,
                "proof_complete": score.proof_complete,
                "proof_partial": score.proof_partial,
                "proof_invalid": score.proof_invalid,
                "rubric_reasons": score.reasons,
                "risk_flags": score.risk_flags,
                "review_feedback": proof_review_feedback(
                    score.risk_flags, score.reasons
                ),
                "manual_review_recommended": True,
                "proof_text": _proof_text(result),
                "final_answer_value": result.final_answer.value,
                "trace_path": str(trace_path or ""),
            }
        )
        rows.append(row if isinstance(row, dict) else {})
    return rows


def render_proof_review_pack(rows: list[dict[str, Any]]) -> str:
    review_count = sum(1 for row in rows if row.get("manual_review_recommended"))
    lines = [
        "# Proof Manual Review Pack",
        "",
        f"- proof_count: {len(rows)}",
        f"- manual_review_recommended_count: {review_count}",
        "",
        "## Review Index",
        "",
        "| Question ID | Domain | Score | Complete | Review | Reasons | Risks |",
        "|---|---|---:|---|---|---|---|",
    ]
    for row in rows:
        reasons = ", ".join(str(x) for x in row.get("rubric_reasons", []))
        risks = ", ".join(str(x) for x in row.get("risk_flags", []))
        lines.append(
            "| {qid} | {domain} | {score:.3f} | {complete} | {review} | {reasons} | {risks} |".format(
                qid=row.get("question_id", ""),
                domain=row.get("domain", ""),
                score=float(row.get("proof_score", 0.0)),
                complete=row.get("proof_complete", False),
                review=row.get("manual_review_recommended", False),
                reasons=reasons or "none",
                risks=risks or "none",
            )
        )

    for row in rows:
        text = str(row.get("proof_text", "")).strip()
        if not text:
            continue
        lines.extend(
            [
                "",
                f"## Proof: {row.get('question_id', '')}",
                "",
                f"- question: {row.get('question', '')}",
                f"- score: {float(row.get('proof_score', 0.0)):.3f}",
                f"- reasons: {', '.join(str(x) for x in row.get('rubric_reasons', [])) or 'none'}",
                f"- risks: {', '.join(str(x) for x in row.get('risk_flags', [])) or 'none'}",
                f"- feedback: {'; '.join(str(x) for x in row.get('review_feedback', [])) or 'none'}",
                "",
                "```text",
                text,
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def write_proof_review_pack(
    results_path: str | Path,
    out_path: str | Path,
    answers_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    rows = build_proof_review_rows(
        results_path=results_path,
        answers_path=answers_path,
        trace_dir=trace_dir,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    safe_text_write(render_proof_review_pack(rows), out)
    safe_text_write(
        json.dumps(rows, ensure_ascii=False, indent=2), out.with_suffix(".json")
    )
    return rows
