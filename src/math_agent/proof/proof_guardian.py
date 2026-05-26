from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .proof_rubric import ProofRubricScore, proof_score_to_metadata


@dataclass
class ProofGuardianDecision:
    enabled: bool
    candidate_id: str | None
    status: str
    score: float
    proof_complete: bool
    proof_partial: bool
    proof_invalid: bool
    allow_finalization: bool
    requires_repair: bool
    selected_reason: str
    risk_flags: list[str]
    reasons: list[str]
    rubric: dict[str, Any] | None


def build_proof_guardian_decision(
    scores: list[ProofRubricScore], allow_partial: bool = False
) -> ProofGuardianDecision:
    if not scores:
        return ProofGuardianDecision(
            False,
            None,
            "no_proof_candidate",
            0.0,
            False,
            False,
            False,
            True,
            False,
            "no_scores",
            [],
            [],
            None,
        )
    complete = sorted(
        [s for s in scores if s.proof_complete], key=lambda s: s.score, reverse=True
    )
    partial = sorted(
        [s for s in scores if s.proof_partial], key=lambda s: s.score, reverse=True
    )
    target = (
        complete[0]
        if complete
        else (
            partial[0]
            if partial
            else sorted(scores, key=lambda s: s.score, reverse=True)[0]
        )
    )
    if target.proof_complete:
        status = "proof_complete"
        allow = True
        repair = False
        reason = "complete_proof_selected"
    elif target.proof_partial:
        status = "proof_partial_allowed" if allow_partial else "proof_partial"
        allow = allow_partial
        repair = not allow_partial
        reason = "partial_proof_selected"
    else:
        status = "proof_invalid"
        allow = False
        repair = True
        reason = "invalid_proof_selected"
    return ProofGuardianDecision(
        True,
        target.candidate_id,
        status,
        target.score,
        target.proof_complete,
        target.proof_partial,
        target.proof_invalid,
        allow,
        repair,
        reason,
        list(target.risk_flags),
        list(target.reasons),
        proof_score_to_metadata(target),
    )


def proof_guardian_decision_to_metadata(
    decision: ProofGuardianDecision,
) -> dict[str, Any]:
    return asdict(decision)
