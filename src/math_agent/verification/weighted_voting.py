from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from math_agent.verification.verifier_scoring import VerifierScore, _candidate_model

VOTE_TIE_EPSILON = 1e-9


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
    models = [
        _candidate_model(candidate, index) for index, candidate in enumerate(candidates)
    ]
    score_by_id = {score.candidate_id.strip(): score for score in scores}
    groups: dict[str, Any] = {}
    for model in models:
        score = score_by_id.get(model.candidate_id.strip())
        if score is None:
            continue
        normalized = (score.normalized_answer or "").strip()
        key = normalized if score.passed and normalized else "__invalid__"
        g = groups.setdefault(
            key,
            {
                "weight": 0.0,
                "candidate_ids": [],
                "top_score": 0.0,
                "selected_answer": None,
                "selected_candidate_id": None,
                "risk_flags": [],
            },
        )
        if key != "__invalid__":
            g["weight"] += score.final_score
        g["candidate_ids"].append(score.candidate_id)
        member_risks = sorted(set(model.risk_flags) | set(score.risk_flags))
        g["risk_flags"] = sorted(set(g["risk_flags"]) | set(member_risks))
        current_id = g["selected_candidate_id"]
        if (
            g["selected_answer"] is None
            or score.final_score > g["top_score"]
            or (
                abs(score.final_score - g["top_score"]) <= VOTE_TIE_EPSILON
                and (current_id is None or score.candidate_id < current_id)
            )
        ):
            g["top_score"] = score.final_score
            g["selected_answer"] = model.final_answer_value
            g["selected_candidate_id"] = score.candidate_id
    return groups


def _candidate_score_alignment_error(
    candidates: list[Any], scores: list[VerifierScore]
) -> str | None:
    models = [
        _candidate_model(candidate, index) for index, candidate in enumerate(candidates)
    ]
    candidate_ids = [model.candidate_id.strip() for model in models]
    score_ids = [score.candidate_id.strip() for score in scores]
    if (
        len(candidates) != len(scores)
        or any(not candidate_id for candidate_id in candidate_ids)
        or any(not score_id for score_id in score_ids)
        or len(candidate_ids) != len(set(candidate_ids))
        or len(score_ids) != len(set(score_ids))
        or set(candidate_ids) != set(score_ids)
    ):
        return "candidate_score_alignment_error"
    return None


def weighted_vote(
    candidates: list[Any], scores: list[VerifierScore], allow_fallback: bool = True
) -> WeightedVoteDecision:
    alignment_error = _candidate_score_alignment_error(candidates, scores)
    if alignment_error:
        return WeightedVoteDecision(
            None,
            None,
            None,
            0.0,
            len(candidates),
            {},
            [asdict(score) for score in scores],
            False,
            allow_fallback,
            [alignment_error],
            [alignment_error],
        )
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
            sorted(
                {
                    "weighted_vote_no_valid_candidate",
                    *(risk for score in scores for risk in score.risk_flags),
                }
            ),
            ["no_valid_candidate"],
        )
    items = sorted(
        valid.items(),
        key=lambda item: (
            -item[1]["weight"],
            -item[1]["top_score"],
            str(item[1]["selected_candidate_id"]),
        ),
    )
    top_key, top = items[0]
    tie = (
        len(items) > 1
        and abs(items[0][1]["weight"] - items[1][1]["weight"]) <= VOTE_TIE_EPSILON
    )
    selected_id = str(top["selected_candidate_id"])
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
        list(top["risk_flags"]),
        [],
    )


def decision_to_metadata(decision: WeightedVoteDecision) -> dict[str, Any]:
    return asdict(decision)
