from __future__ import annotations

import re
from typing import Any

from math_agent.schemas import Verification

_PROOF_CN_KEYWORDS = (
    "证明", "试证", "说明", "推出", "若", "则", "任意", "存在", "唯一", "收敛", "连续", "连通", "子集", "群", "单位元", "拓扑",
)
_PROOF_EN_KEYWORDS = (
    "prove", "show that", "verify that", "for all", "there exists", "unique", "converges", "connected", "subset", "identity element",
)
_PROOF_ROUTE_TYPES = {"proof", "topology", "real_analysis", "abstract_algebra", "set_logic", "number_theory"}


def _to_text(solution_steps: Any) -> str:
    if isinstance(solution_steps, list):
        return "\n".join(str(s) for s in solution_steps if s is not None)
    return str(solution_steps or "")


def detect_proof_problem(question: str, route_info: dict | None = None) -> bool:
    text = (question or "").lower()
    if any(k.lower() in text for k in _PROOF_CN_KEYWORDS + _PROOF_EN_KEYWORDS):
        return True
    info = route_info or {}
    domain = str(info.get("domain", "") or "").lower()
    ptype = str(info.get("problem_type", "") or "").lower()
    return domain in _PROOF_ROUTE_TYPES or ptype in _PROOF_ROUTE_TYPES


def check_proof_structure(question: str, solution_steps: Any) -> Verification:
    text = _to_text(solution_steps)
    issues: list[str] = []
    q = question or ""

    has_givens = any(tok in text for tok in ["设", "已知", "given", "assume", "令"])
    has_goal = any(tok in q for tok in ["证明", "试证", "prove", "show that", "verify that"])
    has_chain = any(tok in text for tok in ["因此", "所以", "则", "implies", "hence", "therefore", "=>"])
    has_conclusion = any(tok in text for tok in ["证毕", "已证", "命题成立", "conclusion", "thus", "qed"])

    if not has_givens:
        issues.append("missing_givens")
    if not has_goal:
        issues.append("missing_goal_statement")
    if not has_chain:
        issues.append("missing_reasoning_chain")
    if not has_conclusion:
        issues.append("missing_conclusion_sentence")

    if re.search(r"\b(assume|suppose).{0,25}(to prove|show)", text.lower()) and re.search(r"\b(therefore|thus).{0,25}(assume|suppose)", text.lower()):
        issues.append("possible_circular_reasoning")
    if re.search(r"\bboxed\s*\{", text) and len(text) > 200:
        issues.append("boxed_not_required_for_proof")
    if re.search(r"\b\d+[\+\-\*/]\d+", q) and "证明" in q:
        issues.append("proof_misread_as_numeric")
    if re.search(r"final_answer\.value\s*=\s*['\"]\s*['\"]", text):
        issues.append("final_answer_value_empty")

    passed = len([i for i in issues if i.startswith("missing_")]) <= 1 and "possible_circular_reasoning" not in issues
    confidence = 0.9 if passed else 0.45
    notes = "ok" if not issues else "issues=" + ",".join(issues)
    return Verification(method="logic_review", passed=passed, notes=f"confidence={confidence}; {notes}")


def proof_final_answer_policy(result):
    final_answer = result.final_answer
    if final_answer.type != "proof":
        return result

    boxed = ""
    value = (final_answer.value or "").strip()
    if not value:
        value = "已证"
    if len(value) > 80:
        value = "命题成立"
    updated = result.model_copy(update={"final_answer": final_answer.model_copy(update={"type": "proof", "value": value, "boxed": boxed})})
    return updated
