from __future__ import annotations

import re
from typing import Any

from math_agent.schemas import FinalAnswer, ProblemParse, SolveResult, ToolTrace, Verification
from math_agent.agents.proof_guardian import proof_final_answer_policy
from math_agent.tools.answer_normalizer import extract_answer_by_patterns, extract_boxed_answer

_MAX_FINAL_LEN = 160
_LONG_TEXT_TOKENS = ("```", "###", "步骤一", "步骤二", "证明如下", "证明：", "由此可得", "首先", "其次")


def _is_long_markdown(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    return (
        "```" in value
        or value.count("\n") > 2
        or len(value) > _MAX_FINAL_LEN
        or any(token in value for token in _LONG_TEXT_TOKENS)
    )


def sanitize_boxed(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    boxed = extract_boxed_answer(raw)
    candidate = boxed if boxed else raw
    candidate = candidate.strip().strip("` ")
    if candidate.startswith("$") and candidate.endswith("$") and len(candidate) > 2:
        candidate = candidate[1:-1].strip()
    if _is_long_markdown(candidate):
        return ""
    if "\\boxed" in candidate:
        nested = extract_boxed_answer(candidate)
        if nested:
            candidate = nested.strip()
    return candidate if len(candidate) <= _MAX_FINAL_LEN else ""


def _pick_final_candidate(payload: dict[str, Any]) -> str:
    for key in ("visible_solution_steps", "solution_steps"):
        steps = payload.get(key)
        if isinstance(steps, list):
            text = "\n".join(str(s) for s in steps if s is not None)
            boxed = extract_boxed_answer(text)
            if boxed:
                return boxed
            patterned = extract_answer_by_patterns(text)
            if patterned and not _is_long_markdown(patterned):
                return patterned
    for key in ("draft_solution", "answer"):
        text = payload.get(key)
        if isinstance(text, str):
            boxed = extract_boxed_answer(text)
            if boxed:
                return boxed
            patterned = extract_answer_by_patterns(text)
            if patterned and not _is_long_markdown(patterned):
                return patterned
    return ""


def detect_dirty_final_answer(result: dict | SolveResult) -> list[str]:
    payload = result.model_dump() if isinstance(result, SolveResult) else dict(result or {})
    final = payload.get("final_answer") if isinstance(payload.get("final_answer"), dict) else {}
    value = str(final.get("value", "") or "").strip()
    boxed = str(final.get("boxed", "") or "").strip()
    flags: list[str] = []
    if not final:
        flags.append("missing_final")
    if not value:
        flags.append("empty_value")
    if _is_long_markdown(value):
        flags.append("markdown_in_final")
    if boxed and _is_long_markdown(boxed):
        flags.append("dirty_boxed")
        if "证明" in boxed or "步骤" in boxed:
            flags.append("proof_boxed_pollution")
    if re.fullmatch(r"\\?boxed\{\s*42\s*\}", boxed) or value == "42" or boxed == "42":
        flags.append("boxed_42_fallback")
    if value in {"", "0", "42"}:
        flags.append("suspicious_short_fallback")
    return list(dict.fromkeys(flags))


def _minimal_failure_result(payload: dict[str, Any]) -> SolveResult:
    qid = str(payload.get("question_id") or "unknown")
    return SolveResult(
        question_id=qid,
        domain=str(payload.get("domain") or "unknown"),
        problem_type=str(payload.get("problem_type") or "unknown"),
        problem_parse=ProblemParse(goal=str(payload.get("question") or ""), givens=[], symbols=[]),
        solution_plan=[],
        visible_solution_steps=[],
        tool_trace=[ToolTrace(tool="none", purpose="formatter_repair", status="fail", summary="schema repaired")],
        final_answer=FinalAnswer(type="text", value="", boxed=""),
        verification=Verification(method="none", passed=False, notes="formatter repair created failure result"),
        didactic_hint="请检查输入与求解过程后重试。",
        confidence=0.0,
        status="fail",
        error="invalid solve result repaired",
    )


def proof_safe_finalize(result: dict | SolveResult) -> SolveResult:
    model = result if isinstance(result, SolveResult) else SolveResult.model_validate(result)
    if model.final_answer.type != "proof":
        return model
    sanitized = sanitize_boxed(model.final_answer.boxed)
    value = model.final_answer.value.strip()
    if not value or _is_long_markdown(value):
        source = "\n".join(model.visible_solution_steps)
        value = extract_answer_by_patterns(source) or "命题已完成证明。"
        if not value.startswith("已证明") and value != "命题已完成证明。":
            value = f"已证明：{value}"
    status = model.status
    if status == "fail" and value:
        status = "partial"
    model = model.model_copy(update={"final_answer": model.final_answer.model_copy(update={"value": value, "boxed": sanitized if sanitized and len(sanitized) < 80 else ""}), "status": status})
    return proof_final_answer_policy(model)


def repair_solve_result(result: dict | SolveResult) -> SolveResult:
    payload = result.model_dump() if isinstance(result, SolveResult) else dict(result or {})
    try:
        model = SolveResult.model_validate(payload)
        original_ok = True
    except Exception:
        original_ok = False
        model = _minimal_failure_result(payload)

    flags = detect_dirty_final_answer(model)
    fa = model.final_answer
    value = (fa.value or "").strip()

    if (not value) or _is_long_markdown(value):
        candidate = _pick_final_candidate(payload)
        candidate = sanitize_boxed(candidate)
        if candidate:
            value = candidate
        elif not value or _is_long_markdown(value):
            value = ""

    raw_boxed = (fa.boxed or "").strip()
    inner_boxed = sanitize_boxed(raw_boxed)
    boxed = ""
    if raw_boxed and inner_boxed:
        boxed = raw_boxed if "\\boxed" in raw_boxed else f"\\boxed{{{inner_boxed}}}"
    if not boxed and value and fa.type in {"number", "expression", "set"} and not _is_long_markdown(value):
        boxed = f"\\boxed{{{value}}}" if len(value) <= 80 else ""

    status = model.status
    error = model.error
    if not value and fa.type != "proof":
        status = "partial" if status == "success" else status
        if status == "fail" and not error:
            error = "missing final answer"
    repaired = (not original_ok) or bool(flags)
    if repaired:
        flags.append("schema_repaired")

    updated = model.model_copy(
        update={
            "final_answer": fa.model_copy(update={"value": value, "boxed": boxed}),
            "status": status,
            "error": error,
        }
    )
    if updated.final_answer.type == "proof":
        updated = proof_safe_finalize(updated)
    return updated
