from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from math_agent.evaluation.judge import (
    exact_match as judge_exact_match,
    normalized_match,
    numeric_match,
    symbolic_match,
)
from math_agent.schemas import SolveResult
from pydantic import ValidationError


def accuracy(correct: int, total: int) -> float:
    return correct / total if total else 0.0


def _safe_rate(n: int, d: int) -> float:
    return n / d if d else 0.0


def load_jsonl(path: str | Path) -> tuple[list[dict], int]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return [], 0

    rows: list[dict] = []
    invalid = 0
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                invalid += 1
    return rows, invalid


def load_answers(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    rows, _ = load_jsonl(path)
    answers: dict[str, str] = {}
    for row in rows:
        qid = str(row.get("question_id", "")).strip()
        ans = str(row.get("answer", ""))
        if qid:
            answers[qid] = ans
    return answers


def evaluate_results(
    results_path: str | Path, answers_path: str | Path | None = None
) -> dict:
    raw_rows, json_invalid = load_jsonl(results_path)
    answers = load_answers(answers_path)

    valid_results: list[SolveResult] = []
    schema_invalid = 0
    for row in raw_rows:
        try:
            valid_results.append(SolveResult.model_validate(row))
        except ValidationError:
            schema_invalid += 1

    total = len(raw_rows) + json_invalid
    json_valid_count = len(valid_results)

    status_counter = Counter(r.status for r in valid_results)
    domain_counter = Counter(r.domain for r in valid_results)
    type_counter = Counter(r.problem_type for r in valid_results)

    verifier_pass = sum(1 for r in valid_results if r.verification.passed)
    avg_conf = (
        sum(r.confidence for r in valid_results) / json_valid_count
        if json_valid_count
        else 0.0
    )

    metrics: dict[str, object] = {
        "total": total,
        "json_valid_count": json_valid_count,
        "json_valid_rate": _safe_rate(json_valid_count, total),
        "json_invalid_count": total - json_valid_count,
        "json_schema_invalid_count": schema_invalid,
        "success_count": status_counter.get("success", 0),
        "partial_count": status_counter.get("partial", 0),
        "fail_count": status_counter.get("fail", 0),
        "verifier_pass_rate": _safe_rate(verifier_pass, json_valid_count),
        "average_confidence": avg_conf,
        "domain_distribution": dict(sorted(domain_counter.items())),
        "problem_type_distribution": dict(sorted(type_counter.items())),
    }

    if answers:
        exact = normalized = numeric = symbolic = matched_items = 0
        for r in valid_results:
            gold = answers.get(r.question_id)
            if gold is None:
                continue
            matched_items += 1
            pred = r.final_answer.value
            exact += int(judge_exact_match(pred, gold))
            normalized += int(normalized_match(pred, gold))
            numeric += int(numeric_match(pred, gold))
            symbolic += int(symbolic_match(pred, gold))

        metrics.update(
            {
                "answer_covered_count": matched_items,
                "exact_match": _safe_rate(exact, matched_items),
                "normalized_match": _safe_rate(normalized, matched_items),
                "numeric_match": _safe_rate(numeric, matched_items),
                "symbolic_match": _safe_rate(symbolic, matched_items),
            }
        )

    return metrics


def render_markdown_report(
    metrics: dict, results_path: str, answers_path: str | None = None
) -> str:
    lines = ["# Evaluation Report", "", f"- Results: `{results_path}`"]
    if answers_path:
        lines.append(f"- Answers: `{answers_path}`")
    lines.extend(["", "## Core Metrics"])

    keys = [
        "total",
        "json_valid_count",
        "json_valid_rate",
        "success_count",
        "partial_count",
        "fail_count",
        "verifier_pass_rate",
        "average_confidence",
    ]
    for k in keys:
        lines.append(f"- **{k}**: {metrics.get(k)}")

    lines.extend(["", "## Domain Distribution"])
    for k, v in metrics.get("domain_distribution", {}).items():
        lines.append(f"- {k}: {v}")

    lines.extend(["", "## Problem Type Distribution"])
    for k, v in metrics.get("problem_type_distribution", {}).items():
        lines.append(f"- {k}: {v}")

    if "exact_match" in metrics:
        lines.extend(["", "## Answer Matching"])
        for k in [
            "answer_covered_count",
            "exact_match",
            "normalized_match",
            "numeric_match",
            "symbolic_match",
        ]:
            lines.append(f"- **{k}**: {metrics.get(k)}")

    return "\n".join(lines) + "\n"


_BOXED_PATTERN = re.compile(r"\\boxed\{([^{}]+)\}")


def normalize_answer(text: Any) -> str:
    if text is None:
        return ""
    if isinstance(text, (int, float)):
        n = float(text)
        return str(int(n)) if n.is_integer() else str(n)

    s = str(text).strip().lower()
    s = _BOXED_PATTERN.sub(r"\1", s)
    s = s.rstrip("。.").strip()

    try:
        n = float(s)
        return str(int(n)) if n.is_integer() else str(n)
    except (ValueError, TypeError):
        return s


def normalized_exact_match(pred: Any, expected: Any) -> bool:
    return normalize_answer(pred) == normalize_answer(expected)


def exact_match(pred: Any, expected: Any) -> bool:
    """Backward-compatible shadow-eval exact-match wrapper."""
    return normalized_exact_match(pred, expected)


def compute_json_valid_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("json_valid", False)) / len(results)


def compute_missing_final_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if not r.get("final_answer_exists", True)) / len(
        results
    )


def compute_dirty_boxed_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("dirty_boxed", False)) / len(results)


def compute_trace_coverage_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("trace_exists", False)) / len(results)


def compute_failure_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(r.get("failure_category", "unknown")) for r in results)
    return dict(sorted(counter.items()))


def _summarize_dimension(results: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, dict[str, int]] = {}
    for r in results:
        k = str(r.get(key, "unknown") or "unknown")
        g = grouped.setdefault(k, {"total": 0, "exact_match_count": 0})
        g["total"] += 1
        g["exact_match_count"] += int(bool(r.get("exact_match", False)))
    out: dict[str, Any] = {}
    for name, d in sorted(grouped.items()):
        total = d["total"]
        out[name] = {
            "total": total,
            "exact_match_count": d["exact_match_count"],
            "exact_match_rate": d["exact_match_count"] / total if total else 0.0,
        }
    return out


def summarize_by_domain(results: list[dict[str, Any]]) -> dict[str, Any]:
    return _summarize_dimension(results, "domain")


def summarize_by_difficulty(results: list[dict[str, Any]]) -> dict[str, Any]:
    return _summarize_dimension(results, "difficulty")
