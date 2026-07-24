from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from math_agent.evaluation.error_taxonomy import FailureCategory, classify_failure
from math_agent.evaluation.metrics import (
    compute_dirty_boxed_rate,
    compute_failure_counts,
    compute_json_valid_rate,
    compute_missing_final_rate,
    compute_trace_coverage_rate,
    exact_match,
    summarize_by_difficulty,
    summarize_by_domain,
)
from math_agent.io_utils import (
    iter_bounded_utf8_lines,
    load_bounded_json,
    strict_json_loads,
)
from math_agent.logging_utils import safe_text_write
from math_agent.security import (
    redact_sensitive_data,
    safe_exception_text,
)


@dataclass
class ShadowEvalCase:
    id: str
    question: str
    expected_answer: str | None = None
    domain: str = "unknown"
    difficulty: str = "unknown"
    answer_type: str = "text"


@dataclass
class ShadowEvalResult:
    id: str
    question: str
    expected_answer: str | None
    predicted_answer: str
    domain: str
    difficulty: str
    answer_type: str
    json_valid: bool = True
    final_answer_exists: bool = True
    dirty_boxed: bool = False
    boxed_42_fallback: bool = False
    trace_exists: bool = False
    trace_complete: bool = False
    verifier_passed: bool | None = None
    repair_used: bool = False
    tool_used: bool = False
    latency_ms: int = 0
    exact_match: bool = False
    status: str = "ok"
    failure_category: str = FailureCategory.OK
    error_message: str = ""


@dataclass
class ShadowEvalSummary:
    total: int
    solved_count: int
    success_count: int
    partial_count: int
    fail_count: int
    exception_count: int
    status_counts: dict[str, int]
    exact_match_count: int
    json_valid_rate: float
    missing_final_count: int
    missing_final_rate: float
    dirty_boxed_count: int
    dirty_boxed_rate: float
    boxed_42_fallback_count: int
    trace_coverage_rate: float
    verifier_failed_count: int
    repair_used_count: int
    tool_usage_rate: float
    average_latency_ms: float
    failure_category_counts: dict[str, int]
    domain_breakdown: dict[str, Any]
    difficulty_breakdown: dict[str, Any]


DEFAULT_CASES = [
    ShadowEvalCase("mock-001", "计算 2+3", "5", "arithmetic", "easy", "number"),
    ShadowEvalCase("mock-002", "解方程 x+1=3", "2", "algebra", "easy", "number"),
    ShadowEvalCase("mock-003", "化简 1/2+1/3", "5/6", "arithmetic", "easy", "fraction"),
    ShadowEvalCase("mock-004", "判断 4 是否为偶数", "yes", "logic", "easy", "boolean"),
    ShadowEvalCase(
        "mock-005",
        "给出一个简短证明：偶数加偶数为偶数",
        None,
        "proof",
        "medium",
        "proof",
    ),
]


def load_cases(
    path: Path | str | None, limit: int | None = None
) -> list[ShadowEvalCase]:
    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 0 <= limit <= 100_000
    ):
        raise ValueError("shadow case limit is outside the safe range")
    if limit == 0:
        return []
    if path is None:
        return DEFAULT_CASES.copy() if limit is None else DEFAULT_CASES[:limit]
    p = Path(path)
    rows: list[dict[str, Any]]
    if p.suffix.lower() == ".json":
        obj = load_bounded_json(p)
        rows = obj if isinstance(obj, list) else [obj]
        if limit is not None:
            rows = rows[:limit]
    else:
        rows = []
        for _, line in iter_bounded_utf8_lines(p):
            if limit is not None and len(rows) >= limit:
                # Reach EOF so the reader can verify the input did not mutate.
                continue
            if not line.strip():
                continue
            value = strict_json_loads(line)
            if not isinstance(value, dict):
                raise ValueError("shadow JSONL rows must be objects")
            rows.append(value)
    return [
        ShadowEvalCase(
            id=str(r["id"]),
            question=str(r["question"]),
            expected_answer=(
                None
                if r.get("expected_answer") is None
                else str(r.get("expected_answer"))
            ),
            domain=str(r.get("domain", "unknown")),
            difficulty=str(r.get("difficulty", "unknown")),
            answer_type=str(r.get("answer_type", "text")),
        )
        for r in rows
    ]


def _mock_runner(case: ShadowEvalCase, _options: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "计算 2+3": "5",
        "解方程 x+1=3": "2",
        "化简 1/2+1/3": "5/6",
        "判断 4 是否为偶数": "yes",
    }
    if case.answer_type == "proof":
        return {
            "predicted_answer": "设 a=2m,b=2n，则 a+b=2(m+n)，故为偶数。",
            "proof_partial": False,
            "verifier_passed": True,
        }
    return {
        "predicted_answer": mapping.get(case.question, "mock-answer"),
        "verifier_passed": True,
    }


def run_shadow_eval(
    cases: list[ShadowEvalCase],
    runner: Callable[[ShadowEvalCase, dict[str, Any]], dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
) -> list[ShadowEvalResult]:
    real_runner = runner or _mock_runner
    opts = options or {}
    out: list[ShadowEvalResult] = []
    for case in cases:
        start = time.perf_counter()
        try:
            rr = real_runner(case, opts) or {}
            predicted_raw = rr.get("predicted_answer", "")
            predicted = predicted_raw if isinstance(predicted_raw, str) else ""
            json_valid_raw = rr.get("json_valid", True)
            final_exists_raw = rr.get("final_answer_exists", predicted.strip() != "")
            verifier_raw = rr.get("verifier_passed")
            status_raw = rr.get("status", "ok")
            res = ShadowEvalResult(
                id=case.id,
                question=case.question,
                expected_answer=case.expected_answer,
                predicted_answer=predicted,
                domain=case.domain,
                difficulty=case.difficulty,
                answer_type=case.answer_type,
                json_valid=(
                    json_valid_raw
                    if isinstance(json_valid_raw, bool)
                    and isinstance(predicted_raw, str)
                    else False
                ),
                final_answer_exists=(
                    final_exists_raw if isinstance(final_exists_raw, bool) else False
                ),
                dirty_boxed=bool(rr.get("dirty_boxed", False)),
                boxed_42_fallback=bool(rr.get("boxed_42_fallback", False)),
                trace_exists=bool(rr.get("trace_exists", False)),
                trace_complete=bool(rr.get("trace_complete", False)),
                verifier_passed=(
                    verifier_raw if isinstance(verifier_raw, bool) else None
                ),
                repair_used=bool(rr.get("repair_used", False)),
                tool_used=bool(rr.get("tool_used", False)),
                status=status_raw if isinstance(status_raw, str) else "fail",
                error_message=str(rr.get("error_message", ""))[:200],
            )
            res.exact_match = bool(
                res.json_valid
                and res.final_answer_exists
                and res.status in {"ok", "success"}
                and res.verifier_passed is True
                and exact_match(res.predicted_answer, case.expected_answer)
            )
            payload = asdict(res)
            for key in (
                "tool_error",
                "formatter_repair_failed",
                "proof_partial",
                "timeout",
            ):
                if key in rr:
                    payload[key] = rr[key]
            res.failure_category = classify_failure(payload)
        except Exception as exc:  # noqa: BLE001
            res = ShadowEvalResult(
                id=case.id,
                question=case.question,
                expected_answer=case.expected_answer,
                predicted_answer="",
                domain=case.domain,
                difficulty=case.difficulty,
                answer_type=case.answer_type,
                json_valid=False,
                final_answer_exists=False,
                verifier_passed=False,
                status="exception",
                failure_category=FailureCategory.EXCEPTION,
                error_message=f"{type(exc).__name__}: {safe_exception_text(exc, 120)}",
            )
        res.latency_ms = int((time.perf_counter() - start) * 1000)
        out.append(res)
    return out


def _is_successful_shadow_result(row: dict[str, Any]) -> bool:
    expected_answer = row.get("expected_answer")
    answer_gate = expected_answer in (None, "") or row.get("exact_match") is True
    return bool(
        row.get("json_valid") is True
        and row.get("final_answer_exists") is True
        and str(row.get("predicted_answer", "")).strip()
        and row.get("status") in {"ok", "success"}
        and row.get("verifier_passed") is True
        and row.get("failure_category") == FailureCategory.OK
        and answer_gate
    )


def summarize_results(results: list[ShadowEvalResult]) -> ShadowEvalSummary:
    rows = [asdict(r) for r in results]
    total = len(results)
    status_counts = Counter(str(row.get("status", "unknown")) for row in rows)
    successful_rows = [row for row in rows if _is_successful_shadow_result(row)]
    return ShadowEvalSummary(
        total=total,
        solved_count=len(successful_rows),
        success_count=len(successful_rows),
        partial_count=status_counts.get("partial", 0),
        fail_count=status_counts.get("fail", 0),
        exception_count=status_counts.get("exception", 0),
        status_counts=dict(sorted(status_counts.items())),
        exact_match_count=sum(1 for r in rows if r.get("exact_match", False)),
        json_valid_rate=compute_json_valid_rate(rows),
        missing_final_count=sum(
            1 for r in rows if not r.get("final_answer_exists", True)
        ),
        missing_final_rate=compute_missing_final_rate(rows),
        dirty_boxed_count=sum(1 for r in rows if r.get("dirty_boxed", False)),
        dirty_boxed_rate=compute_dirty_boxed_rate(rows),
        boxed_42_fallback_count=sum(
            1 for r in rows if r.get("boxed_42_fallback", False)
        ),
        trace_coverage_rate=compute_trace_coverage_rate(rows),
        verifier_failed_count=sum(1 for r in rows if r.get("verifier_passed") is False),
        repair_used_count=sum(1 for r in rows if r.get("repair_used", False)),
        tool_usage_rate=(
            sum(1 for r in rows if r.get("tool_used", False)) / total if total else 0.0
        ),
        average_latency_ms=(
            sum(int(r.get("latency_ms", 0)) for r in rows) / total if total else 0.0
        ),
        failure_category_counts=compute_failure_counts(rows),
        domain_breakdown=summarize_by_domain(rows),
        difficulty_breakdown=summarize_by_difficulty(rows),
    )


def write_jsonl(results: list[ShadowEvalResult], path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    sanitized = redact_sensitive_data([asdict(result) for result in results])
    rows = sanitized if isinstance(sanitized, list) else []
    safe_text_write(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        p,
    )


def write_summary(summary: ShadowEvalSummary, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    sanitized = redact_sensitive_data(asdict(summary))
    safe_text_write(
        json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n",
        p,
    )


def render_markdown_report(
    summary: ShadowEvalSummary, results: list[ShadowEvalResult]
) -> str:
    return (
        "# Shadow Eval Report\n\n"
        "This is NOT official evaluation.\n"
        "This report is for mock / preofficial / shadow validation only.\n"
        "Do not claim official accuracy from this report.\n\n"
        f"- Total: {summary.total}\n"
        f"- Exact Match Count: {summary.exact_match_count}\n"
        f"- JSON Valid Rate: {summary.json_valid_rate:.4f}\n"
        f"- Failure Categories: {summary.failure_category_counts}\n"
        f"- Cases: {len(results)}\n"
    )
