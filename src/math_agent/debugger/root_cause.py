from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RootCauseInfo:
    category: str
    root_cause: str
    owner: str
    action: str


ROOT_CAUSE_MAP: dict[str, RootCauseInfo] = {
    "ok": RootCauseInfo("ok", "no failure", "none", "none"),
    "json_invalid": RootCauseInfo(
        "json_invalid",
        "output serialization / schema violation",
        "formatter / schema",
        "inspect formatter and JSON serialization",
    ),
    "missing_final": RootCauseInfo(
        "missing_final",
        "final answer extraction failed",
        "formatter / final_answer",
        "strengthen final_answer extraction and fallback checks",
    ),
    "dirty_boxed": RootCauseInfo(
        "dirty_boxed",
        "boxed answer contains reasoning or polluted text",
        "formatter",
        "enforce boxed-only answer cleanup",
    ),
    "boxed_42_fallback": RootCauseInfo(
        "boxed_42_fallback",
        "unsafe fallback answer pattern",
        "fallback policy",
        "remove or gate fallback answers",
    ),
    "tool_error": RootCauseInfo(
        "tool_error",
        "tool execution failed",
        "tools",
        "inspect tool error and add tool failure fallback",
    ),
    "verifier_failed": RootCauseInfo(
        "verifier_failed",
        "verifier rejected answer",
        "verifier / solver",
        "compare solver output with verifier notes",
    ),
    "formatter_repair_failed": RootCauseInfo(
        "formatter_repair_failed",
        "formatter repair did not recover valid output",
        "formatter repair",
        "add repair regression case",
    ),
    "proof_partial": RootCauseInfo(
        "proof_partial",
        "proof answer incomplete or not finalizable",
        "proof guardian",
        "add proof rubric / proof completion check",
    ),
    "timeout": RootCauseInfo(
        "timeout",
        "runtime timeout",
        "runtime / budget scheduler",
        "inspect latency and budget policy",
    ),
    "exception": RootCauseInfo(
        "exception",
        "unhandled exception",
        "runtime / harness",
        "inspect error_message and add regression test",
    ),
    "wrong_answer": RootCauseInfo(
        "wrong_answer",
        "predicted answer differs from expected answer",
        "solver / reasoning",
        "inspect domain-specific solver and add candidate case",
    ),
    "unknown": RootCauseInfo(
        "unknown",
        "unknown failure",
        "debugger",
        "improve taxonomy",
    ),
}


P0 = {"json_invalid", "missing_final", "boxed_42_fallback", "exception", "timeout"}
P1 = {"dirty_boxed", "tool_error", "verifier_failed", "formatter_repair_failed"}
P2 = {"wrong_answer", "proof_partial", "unknown"}


def infer_root_cause(case: object) -> RootCauseInfo:
    category = str(getattr(case, "failure_category", "unknown") or "unknown")
    error_message = str(getattr(case, "error_message", "") or "")

    if category in ROOT_CAUSE_MAP:
        base = ROOT_CAUSE_MAP[category]
    else:
        base = ROOT_CAUSE_MAP["unknown"]

    return _refine_by_error_message(category, error_message, base)


def _refine_by_error_message(
    category: str, error_message: str, base: RootCauseInfo
) -> RootCauseInfo:
    if not error_message:
        return base

    msg_lower = error_message.casefold()

    # API / network errors
    if any(
        token in msg_lower
        for token in ("timeout", "timed out", "connection", "rate limit", "429", "503")
    ):
        return RootCauseInfo(
            category=category,
            root_cause="api failure: timeout, rate limit, or connection error",
            owner="api / runtime",
            action="check API health, retry policy, and rate limiting",
        )

    # Token / context window errors
    if any(
        token in msg_lower
        for token in ("context length", "token limit", "max tokens", "truncat")
    ):
        return RootCauseInfo(
            category=category,
            root_cause="context window or token limit exceeded",
            owner="prompt / runtime",
            action="reduce prompt length or increase context budget",
        )

    # JSON / parse errors
    if any(
        token in msg_lower
        for token in ("json", "parse", "schema", "validation", "decode")
    ):
        return RootCauseInfo(
            category=category,
            root_cause="output parsing or JSON schema violation",
            owner="formatter / schema",
            action="inspect malformed output and strengthen JSON repair",
        )

    # Empty response
    if any(
        token in msg_lower
        for token in ("empty", "blank", "null", "none", "missing")
    ):
        return RootCauseInfo(
            category=category,
            root_cause="empty or null model output",
            owner="model / runtime",
            action="add fallback for empty responses",
        )

    return base


def infer_severity(case: object) -> str:
    category = str(getattr(case, "failure_category", "unknown") or "unknown")
    if category in P0:
        return "P0"
    if category in P1:
        return "P1"
    if category in P2:
        return "P2"
    if category == "ok":
        return "none"
    return "P2"
