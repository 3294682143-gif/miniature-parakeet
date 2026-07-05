from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from math_agent.evaluation.error_taxonomy import FailureCategory, classify_failure_taxonomy
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


def load_cases(path: Path | str | None) -> list[ShadowEvalCase]:
    if path is None:
        return DEFAULT_CASES.copy()
    p = Path(path)
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    rows: list[dict[str, Any]]
    if p.suffix.lower() == ".json":
        obj = json.loads(text)
        rows = obj if isinstance(obj, list) else [obj]
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
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
    ablation_level = _options.get("ablation_level", "off")
    mapping = {
        "calculate 2+3": "5",
        "solve x+1=3": "2",
        "simplify 1/2+1/3": "5/6",
        "is 4 even": "yes",
    }
    if case.answer_type == "proof":
        if ablation_level == "off":
            return {
                "predicted_answer": "Let a=2m,b=2n, then a+b=2(m+n), so it is even.",
                "proof_partial": False,
            }
        if ablation_level == "no_verifier":
            return {
                "predicted_answer": "Let a=2m,b=2n, then a+b=2(m+n).",
                "proof_partial": True,
                "verifier_passed": None,
            }
        if ablation_level == "no_tools":
            return {
                "predicted_answer": "Even + even = even.",
                "proof_partial": True,
                "verifier_passed": False,
            }

    base = mapping.get(case.question.casefold(), "mock-answer")
    if ablation_level == "off":
        return {"predicted_answer": base}
    if ablation_level == "no_verifier":
        return {"predicted_answer": base, "verifier_passed": None}
    if ablation_level == "no_tools":
        return {"predicted_answer": base, "tool_used": False, "tool_error": True}
    if ablation_level == "no_formatter":
        return {
            "predicted_answer": base,
            "dirty_boxed": True,
            "final_answer_exists": False,
        }
    return {"predicted_answer": base}


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
            predicted = str(rr.get("predicted_answer", ""))
            res = ShadowEvalResult(
                id=case.id,
                question=case.question,
                expected_answer=case.expected_answer,
                predicted_answer=predicted,
                domain=case.domain,
                difficulty=case.difficulty,
                answer_type=case.answer_type,
                json_valid=bool(rr.get("json_valid", True)),
                final_answer_exists=bool(
                    rr.get("final_answer_exists", predicted.strip() != "")
                ),
                dirty_boxed=bool(rr.get("dirty_boxed", False)),
                boxed_42_fallback=bool(rr.get("boxed_42_fallback", False)),
                trace_exists=bool(rr.get("trace_exists", False)),
                trace_complete=bool(rr.get("trace_complete", False)),
                verifier_passed=rr.get("verifier_passed"),
                repair_used=bool(rr.get("repair_used", False)),
                tool_used=bool(rr.get("tool_used", False)),
                status=str(rr.get("status", "ok")),
                error_message=str(rr.get("error_message", ""))[:200],
            )
            res.exact_match = exact_match(res.predicted_answer, case.expected_answer)
            payload = asdict(res)
            payload.update(rr)
            res.failure_category = classify_failure_taxonomy(payload)
        except Exception as exc:  # noqa: BLE001
            res = ShadowEvalResult(
                id=case.id,
                question=case.question,
                expected_answer=case.expected_answer,
                predicted_answer="",
                domain=case.domain,
                difficulty=case.difficulty,
                answer_type=case.answer_type,
                status="exception",
                failure_category=FailureCategory.EXCEPTION,
                error_message=f"{type(exc).__name__}: {str(exc)[:120]}",
            )
        res.latency_ms = int((time.perf_counter() - start) * 1000)
        out.append(res)
    return out


def summarize_results(results: list[ShadowEvalResult]) -> ShadowEvalSummary:
    rows = [asdict(r) for r in results]
    total = len(results)
    return ShadowEvalSummary(
        total=total,
        solved_count=sum(1 for r in rows if r.get("status") == "ok"),
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
    p.write_text(
        "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in results) + "\n",
        encoding="utf-8",
    )


def write_summary(summary: ShadowEvalSummary, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
