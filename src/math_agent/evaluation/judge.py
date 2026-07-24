from __future__ import annotations

import math
import re
from fractions import Fraction

from math_agent.tools.answer_normalizer import normalize_answer
from math_agent.tools.sympy_tools import check_equivalent

MAX_CANONICAL_ANSWER_CHARS = 1_024


def is_canonical_final_answer(value: str) -> bool:
    text = str(value or "").strip()
    return (
        bool(text)
        and len(text) <= MAX_CANONICAL_ANSWER_CHARS
        and not (
            "\n" in text
            or "\r" in text
            or "\\boxed" in text
            or "```" in text
            or "###" in text
            or re.search(r"\b(?:final\s+answer|answer|result)\s*[:：]", text, re.I)
        )
    )


def exact_match(pred: str, gold: str) -> bool:
    return (pred or "") == (gold or "")


def normalized_match(pred: str, gold: str) -> bool:
    if not is_canonical_final_answer(pred) or not is_canonical_final_answer(gold):
        return False
    normalized_pred = normalize_answer(pred or "").casefold()
    normalized_gold = normalize_answer(gold or "").casefold()
    return (
        bool(normalized_pred and normalized_gold) and normalized_pred == normalized_gold
    )


def numeric_match(pred: str, gold: str, tol: float = 1e-9) -> bool:
    if not is_canonical_final_answer(pred) or not is_canonical_final_answer(gold):
        return False
    p = normalize_answer(pred or "")
    g = normalize_answer(gold or "")

    def _to_float(value: str) -> float | None:
        try:
            return float(value)
        except Exception:
            pass
        try:
            return float(Fraction(value))
        except Exception:
            return None

    pf = _to_float(p)
    gf = _to_float(g)
    if pf is None or gf is None:
        return False
    return math.isclose(pf, gf, rel_tol=tol, abs_tol=tol)


def symbolic_match(pred: str, gold: str) -> bool:
    if not is_canonical_final_answer(pred) or not is_canonical_final_answer(gold):
        return False
    p = normalize_answer(pred or "")
    g = normalize_answer(gold or "")
    return check_equivalent(p, g)
