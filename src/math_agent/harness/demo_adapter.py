from __future__ import annotations

from typing import Any

from math_agent.harness.budget_scheduler import allocate_budget
from math_agent.harness.memory import MemoryHub
from math_agent.harness.skill_registry import SkillRegistry
from math_agent.harness.weighted_voting import select_best_candidate


def _to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        try:
            return result.model_dump()
        except Exception:
            return {}
    if isinstance(result, dict):
        return result
    return {}


def result_to_display_dict(result: Any) -> dict[str, Any]:
    data = _to_dict(result)
    final_answer = data.get("final_answer") if isinstance(data.get("final_answer"), dict) else {}
    verification = data.get("verification") if isinstance(data.get("verification"), dict) else {}
    return {
        "final_answer": str(final_answer.get("value") or ""),
        "status": str(data.get("status") or "unknown"),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
        "verification_method": str(verification.get("method") or "none"),
        "verification_passed": bool(verification.get("passed", False)),
        "risk_flags": safe_get_risk_flags(result),
        "error": str(data.get("error") or ""),
    }


def safe_get_tool_calls(result: Any) -> list[dict[str, Any]]:
    data = _to_dict(result)
    tool_trace = data.get("tool_trace") if isinstance(data.get("tool_trace"), list) else []
    out: list[dict[str, Any]] = []
    for item in tool_trace:
        if isinstance(item, dict):
            out.append(
                {
                    "tool": str(item.get("tool") or "unknown"),
                    "purpose": str(item.get("purpose") or ""),
                    "status": str(item.get("status") or "unknown"),
                    "summary": str(item.get("summary") or ""),
                }
            )
    return out


def safe_get_risk_flags(result: Any) -> list[str]:
    data = _to_dict(result)
    flags: list[str] = []
    raw = data.get("risk_flags")
    if isinstance(raw, list):
        flags.extend(str(x) for x in raw)
    verification = data.get("verification") if isinstance(data.get("verification"), dict) else {}
    issues = verification.get("issues")
    if isinstance(issues, list):
        flags.extend(str(x) for x in issues)
    return list(dict.fromkeys(flags))


def build_demo_timeline(result: Any) -> list[dict[str, str]]:
    tools = safe_get_tool_calls(result)
    display = result_to_display_dict(result)
    return [
        {"stage": "Router", "status": "ok", "detail": "route inferred"},
        {"stage": "Planner", "status": "ok", "detail": "plan created"},
        {"stage": "Solver", "status": "ok", "detail": "draft generated"},
        {"stage": "Tool", "status": "ok" if tools else "skipped", "detail": f"{len(tools)} calls"},
        {"stage": "Verifier", "status": "ok" if display["verification_passed"] else "partial", "detail": display["verification_method"]},
        {"stage": "Refiner", "status": "skipped", "detail": "not always triggered"},
        {"stage": "Formatter", "status": "ok", "detail": "formatter repair"},
        {"stage": "FinalResult", "status": display["status"], "detail": display["final_answer"] or "empty"},
    ]


def load_demo_skill_summary(question: str, route_info: Any = None) -> dict[str, Any]:
    try:
        registry = SkillRegistry()
        route_dict = route_info if isinstance(route_info, dict) else getattr(route_info, "model_dump", lambda: {})()
        skills = registry.list_skills()
        selected = registry.select_skill(route_info=route_dict, question=question)
        selected_meta = registry.safe_load_skill(selected) if selected else None
        return {"skills": skills, "selected_skill": selected, "selected_skill_meta": selected_meta}
    except Exception as exc:
        return {"skills": [], "selected_skill": None, "selected_skill_meta": None, "error": str(exc)}


def load_demo_memory_summary() -> dict[str, Any]:
    try:
        hub = MemoryHub()
        return {"summary": hub.summarize_memory()}
    except Exception as exc:
        return {"summary": {}, "error": str(exc)}


def build_demo_budget_preview(question: str, route_info: Any = None, mode: str = "full") -> dict[str, Any]:
    decision = allocate_budget(question=question, route_info=route_info, mode=mode)
    return {
        "budget_name": decision.budget_name,
        "max_candidates": decision.max_candidates,
        "max_refine_rounds": decision.max_refine_rounds,
        "max_model_calls": decision.max_model_calls,
        "tool_first": decision.tool_first,
        "enable_voting": decision.enable_voting,
        "reason": decision.reason,
        "warnings": decision.warnings,
    }


def build_mock_voting_demo() -> dict[str, Any]:
    candidates = [
        {"candidate_id": "c1", "source": "mock", "answer_type": "number", "final_answer_value": "5", "confidence": 0.9, "verifier_score": 0.9},
        {"candidate_id": "c2", "source": "mock", "answer_type": "number", "final_answer_value": "4", "confidence": 0.6, "verifier_score": 0.4},
    ]
    result = select_best_candidate(candidates)
    return result.model_dump()
