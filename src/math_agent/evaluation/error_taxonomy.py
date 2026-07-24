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
    MALFORMED_JSON = "malformed_json"
    STATUS_FAIL = "status_fail"
    STATUS_PARTIAL = "status_partial"
    WRONG_ANSWER = "wrong_answer"
    UNKNOWN = "unknown"


def classify_failure(result_like: dict[str, Any]) -> str:
    if result_like.get("failure_category") == FailureCategory.MALFORMED_JSON:
        return FailureCategory.MALFORMED_JSON
    if not result_like.get("json_valid", True):
        return FailureCategory.JSON_INVALID
    if not result_like.get("final_answer_exists", True):
        return FailureCategory.MISSING_FINAL
    if result_like.get("dirty_boxed", False):
        return FailureCategory.DIRTY_BOXED
    if result_like.get("boxed_42_fallback", False):
        return FailureCategory.BOXED_42_FALLBACK
    if result_like.get("status") == "exception":
        return FailureCategory.EXCEPTION
    if result_like.get("timeout", False):
        return FailureCategory.TIMEOUT
    if result_like.get("status") == "fail":
        return FailureCategory.STATUS_FAIL
    if result_like.get("status") == "partial":
        return FailureCategory.STATUS_PARTIAL
    if result_like.get("tool_error", False):
        return FailureCategory.TOOL_ERROR
    if result_like.get("verifier_passed") is False:
        return FailureCategory.VERIFIER_FAILED
    if result_like.get("formatter_repair_failed", False):
        return FailureCategory.FORMATTER_REPAIR_FAILED
    if result_like.get("proof_partial", False):
        return FailureCategory.PROOF_PARTIAL
    if (
        result_like.get("expected_answer") not in (None, "")
        and result_like.get("exact_match") is False
    ):
        return FailureCategory.WRONG_ANSWER
    if result_like.get("status") in {"ok", "success"}:
        return FailureCategory.OK
    return FailureCategory.UNKNOWN


def classify_failure_taxonomy(result_like: dict[str, Any]) -> str:
    """Backward-compatible name for callers using the taxonomy terminology."""

    return classify_failure(result_like)
