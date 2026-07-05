from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from math_agent.harness.weighted_voting import (
    normalize_candidate_answer as _normalize_candidate,
)
from math_agent.proof import score_proof_candidate
from math_agent.schemas import CandidateAnswer


@dataclass
class VerifierScore:
    candidate_id: str
    normalized_answer: str
    verifier_level: str
    format_score: float
    consistency_score: float
    tool_score: float
    proof_score: float
    risk_penalty: float
    final_score: float
    passed: bool
    reasons: list[str]


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _candidate_model(candidate: Any, index: int = 0) -> CandidateAnswer:
    if isinstance(candidate, CandidateAnswer):
        return _normalize_candidate(candidate)
    if isinstance(candidate, dict):
        p = dict(candidate)
        p.setdefault("candidate_id", f"candidate-{index}")
        p.setdefault("source", str(p.get("source") or "runtime"))
        return _normalize_candidate(p)
    return _normalize_candidate(
        CandidateAnswer(
            candidate_id=f"candidate-{index}",
            source="runtime",
            final_answer_value=str(candidate or ""),
        )
    )


def normalize_candidate_answer(answer: Any) -> str:
    return (_candidate_model(answer).normalized_answer or "").strip()


def score_candidate(
    candidate: Any,
    verifier_level: str = "basic",
    answer_type: str = "text",
    expected_answer: str | None = None,
) -> VerifierScore:
    m = _candidate_model(candidate)
    n = (m.normalized_answer or "").strip()
    flags = set(m.risk_flags or [])
    reasons = []
    fs = 0.85 if (m.final_answer_value or "").strip() else 0.1
    if "missing_final" in flags:
        fs -= 0.35
    if "dirty_boxed" in flags:
        fs -= 0.2
    if "schema_invalid" in flags:
        fs -= 0.3
    fs = _clamp(fs)
    cs = 0.5 if n else 0.0
    if (
        expected_answer is not None
        and n
        and n == normalize_candidate_answer(expected_answer)
    ):
        cs = 1.0
    method = (m.verification_method or "").lower()
    ts = (
        0.8
        if (
            m.metadata.get("tool_used") is True or "tool" in method or "sympy" in method
        )
        else 0.5
    )
    ps = 0.5
    if (answer_type or "text").lower() == "proof":
        proof_score = score_proof_candidate(
            m, answer_type="proof", candidate_id=m.candidate_id
        )
        ps = proof_score.score
        flags.update(proof_score.risk_flags)
        reasons.extend([f"proof_rubric:{r}" for r in proof_score.reasons])
        if proof_score.proof_partial:
            ps -= 0.05
        if proof_score.proof_invalid:
            ps -= 0.2
    ps = _clamp(ps)
    penalties = {
        "dirty_boxed": 0.1,
        "boxed_42_fallback": 0.3,
        "schema_invalid": 0.25,
        "exception": 0.2,
    }
    rp = min(0.8, sum(v for k, v in penalties.items() if k in flags))
    final = _clamp(0.4 * fs + 0.3 * cs + 0.15 * ts + 0.15 * ps - rp)
    passed = final >= 0.5 and bool(n)
    if not passed:
        reasons.append("score_below_threshold_or_empty_answer")
    return VerifierScore(
        m.candidate_id, n, verifier_level, fs, cs, ts, ps, rp, final, passed, reasons
    )


def score_candidates(
    candidates: list[Any],
    verifier_level: str = "basic",
    answer_type: str = "text",
    expected_answer: str | None = None,
) -> list[VerifierScore]:
    return [
        score_candidate(c, verifier_level, answer_type, expected_answer)
        for c in candidates
    ]


def score_to_metadata(score: VerifierScore) -> dict[str, Any]:
    return asdict(score)
