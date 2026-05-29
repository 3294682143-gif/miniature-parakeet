from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, cast

import sympy as sp  # type: ignore[import-untyped]

from math_agent.tools.answer_normalizer import normalize_answer


def exact_match(pred: str, gold: str) -> bool:
    return (pred or "") == (gold or "")


def normalized_match(pred: str, gold: str) -> bool:
    return (
        normalize_answer(pred or "").casefold()
        == normalize_answer(gold or "").casefold()
    )


def numeric_match(pred: str, gold: str, tol: float = 1e-9) -> bool:
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
    p = normalize_answer(pred or "")
    g = normalize_answer(gold or "")
    local_symbols = {"e": sp.E, "E": sp.E}
    sympify_any = cast(Any, sp.sympify)
    try:
        pexpr = cast(Any, sympify_any(p, locals=local_symbols))
        gexpr = cast(Any, sympify_any(g, locals=local_symbols))
    except Exception:
        return False
    try:
        return bool(sp.simplify(pexpr - gexpr) == 0)
    except Exception:
        return False
