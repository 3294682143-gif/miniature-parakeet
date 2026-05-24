from __future__ import annotations

from typing import Any


class FailureCategory:
    OK = "ok"
    JSON_INVALID = "json_invalid"
    MISSING_FINAL = "missing_final"
    DIRTY_BOXED = "dirty_boxed"
    BOXED_42_FALLBACK = "boxed_42_fallback"
    TOOL_ERROR = "tool_error"
    VERIFIER_FAILED = "verifier_failed"
    FORMATTER_REPAIR_FAILED = "formatter_repair_failed"
    PROOF_PARTIAL = "proof_partial"
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    WRONG_ANSWER = "wrong_answer"
    UNKNOWN = "unknown"


def classify_failure(result_like: dict[str, Any]) -> str:
    if not result_like.get("json_valid", True):
        return FailureCategory.JSON_INVALID
    if not result_like.get("final_answer_exists", True):
        return FailureCategory.MISSING_FINAL
    if result_like.get("dirty_boxed", False):
        return FailureCategory.DIRTY_BOXED
    if result_like.get("boxed_42_fallback", False):
        return FailureCategory.BOXED_42_FALLBACK
    if result_like.get("tool_error", False):
        return FailureCategory.TOOL_ERROR
    if result_like.get("verifier_passed") is False:
        return FailureCategory.VERIFIER_FAILED
    if result_like.get("formatter_repair_failed", False):
        return FailureCategory.FORMATTER_REPAIR_FAILED
    if result_like.get("proof_partial", False):
        return FailureCategory.PROOF_PARTIAL
    if result_like.get("timeout", False):
        return FailureCategory.TIMEOUT
    if result_like.get("status") == "exception":
        return FailureCategory.EXCEPTION
    if (
        result_like.get("expected_answer") not in (None, "")
        and result_like.get("exact_match") is False
    ):
        return FailureCategory.WRONG_ANSWER
    if result_like.get("status") in {"ok", "success"}:
        return FailureCategory.OK
    return FailureCategory.UNKNOWN
