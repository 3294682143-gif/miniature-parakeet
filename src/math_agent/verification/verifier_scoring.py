from __future__ import annotations

import math
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
    risk_flags: list[str]
    reasons: list[str]


def _clamp(v: float) -> float:
    try:
        value = float(v)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


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
    candidate_mapping = candidate if isinstance(candidate, dict) else None
    verifier_signal_explicit = isinstance(candidate, CandidateAnswer) or bool(
        candidate_mapping is not None
        and (
            "verifier_score" in candidate_mapping
            or "verification_passed" in candidate_mapping
        )
    )
    verification_passed_explicit = bool(
        (
            isinstance(candidate, CandidateAnswer)
            and "verification_passed" in candidate.model_fields_set
        )
        or (
            candidate_mapping is not None and "verification_passed" in candidate_mapping
        )
    )
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
    cs = _clamp(m.verifier_score) if verifier_signal_explicit else (0.8 if n else 0.0)
    if verification_passed_explicit and m.verification_passed:
        cs = max(cs, 1.0)
    expected_match = bool(
        expected_answer is not None
        and n
        and n == normalize_candidate_answer(expected_answer)
    )
    if not verifier_signal_explicit and expected_match:
        cs = 1.0
    if not verification_passed_explicit:
        flags.add("verifier_missing")
        reasons.append("verifier_signal_missing")
    elif not m.verification_passed:
        flags.add("verifier_failed")
        reasons.append("explicit_verifier_failure")
    method = (m.verification_method or "").lower()
    tool_used = bool(
        m.metadata.get("tool_used") is True or "tool" in method or "sympy" in method
    )
    tool_status = str(
        m.metadata.get("tool_status") or m.metadata.get("tool_call_status") or ""
    ).lower()
    if not tool_used:
        ts = 0.5
    elif tool_status == "success" or (not tool_status and m.verification_passed):
        ts = 0.8
    elif (
        tool_status in {"fail", "failed", "error", "timeout"}
        or not m.verification_passed
    ):
        ts = 0.1
        flags.add("tool_failed")
        reasons.append("tool_signal_failed")
    else:
        ts = 0.4
        flags.add("tool_status_unknown")
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
        "tool_failed": 0.15,
        "verifier_failed": 0.35,
        "verifier_missing": 0.35,
    }
    rp = min(0.8, sum(v for k, v in penalties.items() if k in flags))
    final = _clamp(0.4 * fs + 0.3 * cs + 0.15 * ts + 0.15 * ps - rp)
    normalized_level = (verifier_level or "basic").strip().lower()
    thresholds = {"basic": 0.5, "strong": 0.6, "strict": 0.7}
    if normalized_level not in thresholds:
        normalized_level = "basic"
        flags.add("invalid_verifier_level")
        reasons.append("invalid_verifier_level_fell_back_to_basic")
    passed = bool(
        final >= thresholds[normalized_level]
        and n
        and (m.verification_passed is True or expected_match)
    )
    if not passed:
        reasons.append("score_below_threshold_or_empty_answer")
    return VerifierScore(
        candidate_id=m.candidate_id,
        normalized_answer=n,
        verifier_level=normalized_level,
        format_score=fs,
        consistency_score=cs,
        tool_score=ts,
        proof_score=ps,
        risk_penalty=rp,
        final_score=final,
        passed=passed,
        risk_flags=sorted(flags),
        reasons=reasons,
    )


def score_candidates(
    candidates: list[Any],
    verifier_level: str = "basic",
    answer_type: str = "text",
    expected_answer: str | None = None,
) -> list[VerifierScore]:
    prepared: list[Any] = []
    for index, candidate in enumerate(candidates):
        if isinstance(candidate, dict):
            payload = dict(candidate)
            payload.setdefault("candidate_id", f"candidate-{index}")
            payload.setdefault("source", str(payload.get("source") or "runtime"))
            prepared.append(payload)
        elif isinstance(candidate, CandidateAnswer):
            prepared.append(candidate)
        else:
            prepared.append(
                {
                    "candidate_id": f"candidate-{index}",
                    "source": "runtime",
                    "final_answer_value": str(candidate or ""),
                }
            )
    return [
        score_candidate(candidate, verifier_level, answer_type, expected_answer)
        for candidate in prepared
    ]


def score_to_metadata(score: VerifierScore) -> dict[str, Any]:
    return asdict(score)
