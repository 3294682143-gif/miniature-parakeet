from __future__ import annotations

import re
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
    has_quantifier: bool
    has_case_split: bool
    has_induction: bool
    has_contradiction_method: bool
    contradiction_risk: bool
    circular_reasoning_risk: bool
    shallow_assertion_risk: bool
    empty_or_too_short: bool
    proof_complete: bool
    proof_partial: bool
    proof_invalid: bool
    score: float
    reasons: list[str]
    risk_flags: list[str]


_LEGACY_ASSUMPTION = ("璁", "设", "鍋囪", "浠")
_LEGACY_CHAIN = ("因为", "由于", "因此", "所以", "故", "推出", "鍥", "鎵", "鏁", "鎺")
_LEGACY_CONCLUSION = (
    "证毕",
    "已证",
    "成立",
    "结论",
    "璇佹瘯",
    "宸茶瘉",
    "鎴愮珛",
    "缁",
)
_LEGACY_CLAIM = ("证明", "命题", "璇佹槑", "鍛介")
_LEGACY_QUANTIFIER = ("任意", "存在", "所有", "对任意", "浠绘剰", "瀛樺湪")


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _sentence_count(text: str) -> int:
    parts = re.split(r"[.;。；\n]+", text)
    return len([part for part in parts if part.strip()])


def _marker_count(text: str, markers: tuple[str, ...]) -> int:
    return sum(text.count(marker) for marker in markers)


def extract_proof_text(candidate: Any) -> str:
    if isinstance(candidate, str):
        return candidate.strip()
    if isinstance(candidate, dict):
        for k in [
            "proof_text",
            "visible_solution",
            "final_answer_value",
            "final_answer",
            "value",
            "text",
        ]:
            v = candidate.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, list):
                joined = "\n".join(str(item) for item in v if item is not None)
                if joined.strip():
                    return joined.strip()
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

    assumption_words = (
        "assume",
        "suppose",
        "let",
        "take",
        "fix",
        "choose",
        "given",
        "use",
        "using",
    )
    chain_words = (
        "because",
        "since",
        "therefore",
        "hence",
        "thus",
        "then",
        "implies",
        "so",
        "as a result",
        "it follows",
        "by",
        "step",
        "substitute",
        "simplify",
        "binomial theorem",
        "pascal",
        "divides",
        "congruent",
        "similar",
        "parallel",
        "perpendicular",
    )
    conclusion_words = (
        "therefore",
        "hence",
        "thus",
        "qed",
        "as required",
        "we conclude",
        "this proves",
        "proved",
    )
    claim_words = ("prove", "show that", "claim", "theorem", "lemma", "conclusion")
    quantifier_words = (
        "for all",
        "for every",
        "every",
        "any",
        "there exists",
        "arbitrary",
        "unique",
    )

    chain_marker_count = sum(1 for word in chain_words if word in low) + _marker_count(
        text, _LEGACY_CHAIN
    )
    has_assumption = _has_word(low, assumption_words) or _has_any(
        text, _LEGACY_ASSUMPTION
    )
    has_reasoning_chain = chain_marker_count > 0 or any(
        marker in text for marker in ["=>", "->", "⇒", "→"]
    )
    has_conclusion = _has_any(low, conclusion_words) or _has_any(
        text, _LEGACY_CONCLUSION
    )
    has_claim = (
        has_conclusion or _has_any(low, claim_words) or _has_any(text, _LEGACY_CLAIM)
    )
    uses_symbols = bool(re.search(r"[=<>≤≥∈∉⊂⊆∩∪∑√^]|\b\d+\b|=>|->", text))
    has_quantifier = _has_any(low, quantifier_words) or _has_any(
        text, _LEGACY_QUANTIFIER
    )
    has_case_split = _has_any(low, ("case ", "cases", "split into")) or _has_any(
        text, ("情况", "分类", "分情况")
    )
    has_induction = _has_any(
        low, ("induction", "base case", "inductive step", "induction hypothesis")
    ) or _has_any(text, ("归纳", "基例", "归纳假设"))
    has_contradiction_method = "contradiction" in low and _has_any(
        low, ("assume", "suppose", "contrary", "toward contradiction")
    )

    contradiction_risk = "contradiction" in low and not has_contradiction_method
    circular_reasoning_risk = any(
        phrase in low
        for phrase in [
            "assume what we want to prove",
            "because the conclusion is true",
            "by the desired result",
            "this is true because it is true",
        ]
    ) or _has_any(text, ("因为结论成立", "由待证结论可知"))
    shallow_assertion_risk = (
        _has_any(low, ("obvious", "clearly", "trivial", "it is easy to see"))
        and chain_marker_count < 2
    ) or (len(text.strip()) < 80 and not uses_symbols)
    empty_or_too_short = len(text.strip()) < 8

    score = 0.05 if empty_or_too_short else 0.25
    if has_assumption:
        score += 0.12
    if has_reasoning_chain:
        score += 0.22 + min(chain_marker_count, 4) * 0.03
    if has_conclusion:
        score += 0.16
    if has_claim:
        score += 0.08
    if uses_symbols:
        score += 0.05
    if has_quantifier:
        score += 0.04
    if has_case_split:
        score += 0.05
    if has_induction:
        score += 0.08
    if has_contradiction_method:
        score += 0.06
    if _sentence_count(text) >= 3:
        score += 0.06

    if contradiction_risk:
        score -= 0.35
        risk_flags.append("proof_contradiction_risk")
    if circular_reasoning_risk:
        score -= 0.45
        risk_flags.append("proof_circular_reasoning_risk")
    if shallow_assertion_risk:
        score -= 0.05
        risk_flags.append("proof_shallow_assertion")
    if empty_or_too_short:
        score -= 0.25
        risk_flags.append("proof_empty")

    score = max(0.0, min(1.0, score))
    proof_invalid = (
        empty_or_too_short
        or circular_reasoning_risk
        or contradiction_risk
        or score < 0.35
    )
    proof_complete = (
        (not proof_invalid)
        and has_reasoning_chain
        and has_conclusion
        and score >= 0.68
        and not shallow_assertion_risk
    )
    proof_partial = (not proof_invalid) and not proof_complete

    if empty_or_too_short:
        reasons.append("proof_empty_or_too_short")
    if shallow_assertion_risk:
        reasons.append("proof_shallow_assertion")
    if circular_reasoning_risk:
        reasons.append("proof_circular_reasoning_risk")
    if contradiction_risk:
        reasons.append("proof_contradiction_risk")
    if proof_partial:
        reasons.append("proof_partial_structure")
        risk_flags.append("proof_partial")
    if proof_invalid:
        reasons.append("proof_invalid")
        risk_flags.append("proof_invalid")
    if proof_complete:
        reasons.append("proof_complete")

    return ProofRubricScore(
        str(cid),
        answer_type,
        text,
        has_claim,
        has_assumption,
        has_reasoning_chain,
        has_conclusion,
        uses_symbols,
        has_quantifier,
        has_case_split,
        has_induction,
        has_contradiction_method,
        contradiction_risk,
        circular_reasoning_risk,
        shallow_assertion_risk,
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
