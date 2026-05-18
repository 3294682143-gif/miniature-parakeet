from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from math_agent.harness.formatter_repair import detect_dirty_final_answer
from math_agent.schemas import CandidateAnswer, SolveResult, WeightedVoteResult
from math_agent.tools.answer_normalizer import normalize_answer, normalize_number


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_risk_flags(candidate: CandidateAnswer) -> list[str]:
    flags = list(candidate.risk_flags or [])
    if not (candidate.final_answer_value or "").strip() and "missing_final" not in flags:
        flags.append("missing_final")
    return list(dict.fromkeys(flags))


def normalize_candidate_answer(candidate: CandidateAnswer | dict[str, Any]) -> CandidateAnswer:
    try:
        model = candidate if isinstance(candidate, CandidateAnswer) else CandidateAnswer.model_validate(candidate)
    except ValidationError:
        raw = dict(candidate) if isinstance(candidate, dict) else {}
        model = CandidateAnswer(
            candidate_id=str(raw.get("candidate_id") or "invalid"),
            source=str(raw.get("source") or "unknown"),
            answer_type=str(raw.get("answer_type") or "text"),
            final_answer_value=str(raw.get("final_answer_value") or ""),
            normalized_answer="",
            confidence=0.0,
            verifier_score=0.0,
            risk_score=1.0,
            risk_flags=["schema_invalid"],
        )

    value = (model.final_answer_value or "").strip()
    normalized = ""
    if value:
        try:
            if model.answer_type == "number":
                normalized = normalize_number(value)
            elif model.answer_type in {"expression", "set", "algorithm"}:
                normalized = normalize_answer(value)
            else:
                normalized = value
        except Exception:
            normalized = value

    dirty_payload = {
        "final_answer": {"value": model.final_answer_value or "", "boxed": model.final_answer_boxed or ""},
    }
    dirty_flags = detect_dirty_final_answer(dirty_payload)
    flags = list(dict.fromkeys((model.risk_flags or []) + dirty_flags))
    if not normalized:
        flags.append("missing_final")

    return model.model_copy(update={"normalized_answer": normalized, "risk_flags": list(dict.fromkeys(flags))})


def cluster_candidates(candidates: list[CandidateAnswer]) -> list[dict[str, Any]]:
    clusters: dict[str, list[CandidateAnswer]] = {}
    for c in candidates:
        n = (c.normalized_answer or "").strip()
        key = "__invalid__" if not n else (f"__free_text__:{c.candidate_id}" if c.answer_type in {"proof", "text"} else n)
        clusters.setdefault(key, []).append(c)

    out: list[dict[str, Any]] = []
    for i, (key, items) in enumerate(clusters.items(), start=1):
        all_flags: list[str] = []
        for item in items:
            all_flags.extend(_safe_risk_flags(item))
        out.append(
            {
                "cluster_id": f"cluster_{i}",
                "normalized_answer": "" if key == "__invalid__" else (items[0].normalized_answer or ""),
                "candidate_ids": [x.candidate_id for x in items],
                "size": len(items),
                "best_verifier_score": max(_to_float(x.verifier_score) for x in items),
                "average_confidence": sum(_to_float(x.confidence) for x in items) / max(len(items), 1),
                "risk_flags": sorted(set(all_flags)),
                "is_invalid": key == "__invalid__",
            }
        )
    return out


def score_candidate(candidate: CandidateAnswer, cluster: dict[str, Any] | None = None) -> float:
    verifier = max(0.0, min(1.0, _to_float(candidate.verifier_score)))
    confidence = max(0.0, min(1.0, _to_float(candidate.confidence)))
    risk_score = max(0.0, min(1.0, _to_float(candidate.risk_score)))
    cluster_size = int((cluster or {}).get("size") or 1)
    cluster_bonus = min(1.0, math.log2(cluster_size + 1) / 2.0)
    valid_bonus = 1.0 if (candidate.normalized_answer or "").strip() else 0.0

    score = 0.45 * verifier + 0.25 * confidence + 0.15 * cluster_bonus + 0.15 * valid_bonus
    score -= risk_score * 0.20

    flags = set(_safe_risk_flags(candidate))
    penalties = {
        "missing_final": 0.35,
        "empty_value": 0.25,
        "dirty_boxed": 0.25,
        "boxed_42_fallback": 0.40,
        "markdown_in_final": 0.20,
        "schema_invalid": 0.30,
    }
    for k, v in penalties.items():
        if k in flags:
            score -= v
    if verifier < 0.2:
        score -= 0.2
    return max(0.0, min(1.0, score))


def select_best_candidate(candidates: list[CandidateAnswer | dict[str, Any]]) -> WeightedVoteResult:
    normalized = [normalize_candidate_answer(c) for c in candidates]
    if not normalized:
        return WeightedVoteResult(selected_candidate_id=None, selected_answer="", confidence=0.0, need_more_verification=True, issues=["no_valid_candidate"], cluster_summary=[])

    clusters = cluster_candidates(normalized)
    cid_to_cluster = {cid: cl for cl in clusters for cid in cl["candidate_ids"]}

    scored: list[tuple[CandidateAnswer, float]] = []
    for c in normalized:
        score = score_candidate(c, cid_to_cluster.get(c.candidate_id))
        scored.append((c, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    best, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0

    issues: list[str] = []
    if best_score <= 0.0 or not (best.normalized_answer or "").strip():
        return WeightedVoteResult(selected_candidate_id=None, selected_answer="", confidence=0.0, need_more_verification=True, issues=["no_valid_candidate"], cluster_summary=build_cluster_summary(normalized))

    if best.verifier_score < 0.3:
        issues.append("low_verifier_top1")
    need_more = (best_score - second_score) < 0.08 or best.verifier_score < 0.45
    if need_more:
        issues.append("close_competition")

    return WeightedVoteResult(
        selected_candidate_id=best.candidate_id,
        selected_answer=best.normalized_answer or best.final_answer_value,
        confidence=max(0.0, min(1.0, best_score)),
        need_more_verification=need_more,
        issues=issues,
        cluster_summary=build_cluster_summary(normalized),
    )


def build_cluster_summary(candidates: list[CandidateAnswer]) -> list[dict[str, Any]]:
    clusters = cluster_candidates(candidates)
    summary: list[dict[str, Any]] = []
    for c in clusters:
        summary.append(
            {
                "cluster_id": c["cluster_id"],
                "answer": c["normalized_answer"],
                "size": c["size"],
                "best_verifier_score": c["best_verifier_score"],
                "risk_flags": c["risk_flags"],
                "is_invalid": c["is_invalid"],
            }
        )
    return summary


def make_candidate_from_solve_result(result: SolveResult | dict[str, Any], candidate_id: str, source: str) -> CandidateAnswer:
    try:
        model = result if isinstance(result, SolveResult) else SolveResult.model_validate(result)
        raw_flags = detect_dirty_final_answer(model)
        verifier_score = 1.0 if model.verification.passed else 0.35
        if model.verification.method in {"logic_review", "symbolic_check", "numeric_check", "substitution"}:
            verifier_score = max(verifier_score, 0.55 if model.verification.passed else 0.25)
        return normalize_candidate_answer(
            CandidateAnswer(
                candidate_id=candidate_id,
                source=source,
                answer_type=model.final_answer.type,
                final_answer_value=model.final_answer.value,
                final_answer_boxed=model.final_answer.boxed,
                normalized_answer="",
                confidence=model.confidence,
                verifier_score=verifier_score,
                risk_score=0.0 if model.status == "success" else 0.35,
                risk_flags=raw_flags,
                verification_method=model.verification.method,
                verification_passed=model.verification.passed,
            )
        )
    except Exception:
        return normalize_candidate_answer(
            CandidateAnswer(
                candidate_id=candidate_id,
                source=source,
                answer_type="text",
                final_answer_value="",
                normalized_answer="",
                confidence=0.0,
                verifier_score=0.0,
                risk_score=1.0,
                risk_flags=["schema_invalid", "missing_final"],
            )
        )
