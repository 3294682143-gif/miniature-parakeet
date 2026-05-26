from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from math_agent.verification.verifier_scoring import VerifierScore, _candidate_model


@dataclass
class WeightedVoteDecision:
    selected_candidate_id: str | None
    selected_answer: str | None
    selected_normalized_answer: str | None
    confidence: float
    candidate_count: int
    answer_groups: dict[str, Any]
    verifier_scores: list[dict[str, Any]]
    tie_break_used: bool
    fallback_used: bool
    risk_flags: list[str]
    reasons: list[str]


def group_candidates_by_normalized_answer(
    candidates: list[Any], scores: list[VerifierScore]
) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for i, (cand, score) in enumerate(zip(candidates, scores)):
        key = (score.normalized_answer or "").strip() or "__invalid__"
        m = _candidate_model(cand, i)
        g = groups.setdefault(
            key,
            {
                "weight": 0.0,
                "candidate_ids": [],
                "top_score": 0.0,
                "selected_answer": m.final_answer_value,
            },
        )
        g["weight"] += score.final_score
        g["candidate_ids"].append(score.candidate_id)
        g["top_score"] = max(g["top_score"], score.final_score)
    return groups


def weighted_vote(
    candidates: list[Any], scores: list[VerifierScore], allow_fallback: bool = True
) -> WeightedVoteDecision:
    groups = group_candidates_by_normalized_answer(candidates, scores)
    valid = {k: v for k, v in groups.items() if k != "__invalid__" and v["weight"] > 0}
    if not valid:
        return WeightedVoteDecision(
            None,
            None,
            None,
            0.0,
            len(candidates),
            groups,
            [asdict(s) for s in scores],
            False,
            allow_fallback,
            ["weighted_vote_no_valid_candidate"],
            ["no_valid_candidate"],
        )
    items = sorted(
        valid.items(),
        key=lambda kv: (
            kv[1]["weight"],
            kv[1]["top_score"],
            sorted(kv[1]["candidate_ids"])[0],
        ),
        reverse=True,
    )
    top_key, top = items[0]
    tie = len(items) > 1 and abs(items[0][1]["weight"] - items[1][1]["weight"]) < 1e-12
    selected_id = sorted(top["candidate_ids"])[0]
    total = sum(v["weight"] for v in valid.values())
    return WeightedVoteDecision(
        selected_id,
        top.get("selected_answer") or top_key,
        top_key,
        (top["weight"] / total if total > 0 else 0.0),
        len(candidates),
        groups,
        [asdict(s) for s in scores],
        tie,
        False,
        [],
        [],
    )


def decision_to_metadata(decision: WeightedVoteDecision) -> dict[str, Any]:
    return asdict(decision)
