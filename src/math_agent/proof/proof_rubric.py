from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ProofRubricScore:
    candidate_id: str
    answer_type: str
    proof_text: str
    has_claim: bool
    has_assumption: bool
    has_reasoning_chain: bool
    has_conclusion: bool
    uses_symbols: bool
    contradiction_risk: bool
    circular_reasoning_risk: bool
    empty_or_too_short: bool
    proof_complete: bool
    proof_partial: bool
    proof_invalid: bool
    score: float
    reasons: list[str]
    risk_flags: list[str]


def extract_proof_text(candidate: Any) -> str:
    if isinstance(candidate, str):
        return candidate.strip()
    if isinstance(candidate, dict):
        for k in ["proof_text", "final_answer_value", "final_answer", "value", "text"]:
            v = candidate.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                nested = v.get("value")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
        return ""
    value = getattr(candidate, "proof_text", None) or getattr(
        candidate, "final_answer_value", None
    )
    if isinstance(value, str):
        return value.strip()
    final_answer = getattr(candidate, "final_answer", None)
    if isinstance(final_answer, dict):
        v = final_answer.get("value")
        if isinstance(v, str):
            return v.strip()
    if isinstance(final_answer, str):
        return final_answer.strip()
    return ""


def score_proof_candidate(
    candidate: Any, answer_type: str = "proof", candidate_id: str | None = None
) -> ProofRubricScore:
    text = extract_proof_text(candidate)
    cid = (
        candidate_id
        or (
            candidate.get("candidate_id")
            if isinstance(candidate, dict)
            else getattr(candidate, "candidate_id", None)
        )
        or "candidate-0"
    )
    low = text.lower()
    reasons: list[str] = []
    risk_flags: list[str] = []
    has_assumption = any(k in text for k in ["设", "假设", "令", "assume"])
    has_reasoning_chain = any(
        k in text
        for k in ["因为", "因此", "所以", "故", "推出", "then", "thus", "hence", "证明"]
    )
    has_conclusion = any(
        k in text for k in ["所以", "故", "因此", "综上", "证毕", "hence", "therefore"]
    )
    has_claim = has_conclusion or any(
        k in text for k in ["结论", "命题", "prove", "show that", "得"]
    )
    uses_symbols = any(k in text for k in ["=", "=>", "→", "∴", "∵", "∀", "∃"])
    contradiction_risk = ("矛盾" in text and "不矛盾" not in text) or (
        "contradiction" in low and "no contradiction" not in low
    )
    circular_reasoning_risk = ("因为结论成立" in text) or (
        "assume what we want to prove" in low
    )
    empty_or_too_short = len(text.strip()) < 12
    score = 0.1 if empty_or_too_short else 0.4
    if has_assumption:
        score += 0.15
    if has_reasoning_chain:
        score += 0.2
    if has_conclusion:
        score += 0.2
    if has_claim:
        score += 0.1
    if uses_symbols:
        score += 0.05
    if contradiction_risk:
        score -= 0.45
        risk_flags.append("proof_contradiction_risk")
    if circular_reasoning_risk:
        score -= 0.25
        risk_flags.append("proof_circular_reasoning_risk")
    score = max(0.0, min(1.0, score))
    proof_invalid = empty_or_too_short or contradiction_risk or score < 0.35
    proof_complete = (
        (not proof_invalid) and has_reasoning_chain and has_conclusion and score >= 0.65
    )
    proof_partial = (not proof_invalid) and (
        0.35 <= score < 0.65 or (has_claim and not has_reasoning_chain)
    )
    if empty_or_too_short:
        reasons.append("proof_empty_or_too_short")
        risk_flags.append("proof_empty")
    if proof_partial:
        reasons.append("proof_partial_structure")
        risk_flags.append("proof_partial")
    if proof_invalid:
        reasons.append("proof_invalid")
        risk_flags.append("proof_invalid")
    if proof_complete:
        reasons.append("proof_complete")
    return ProofRubricScore(
        cid,
        answer_type,
        text,
        has_claim,
        has_assumption,
        has_reasoning_chain,
        has_conclusion,
        uses_symbols,
        contradiction_risk,
        circular_reasoning_risk,
        empty_or_too_short,
        proof_complete,
        proof_partial,
        proof_invalid,
        score,
        reasons,
        sorted(set(risk_flags)),
    )


def score_proof_candidates(
    candidates: list[Any], answer_type: str = "proof"
) -> list[ProofRubricScore]:
    return [
        score_proof_candidate(c, answer_type=answer_type, candidate_id=f"candidate-{i}")
        for i, c in enumerate(candidates)
    ]


def proof_score_to_metadata(score: ProofRubricScore) -> dict[str, Any]:
    return asdict(score)
