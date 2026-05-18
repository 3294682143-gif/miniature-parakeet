from __future__ import annotations

from typing import Any


def _pick(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def build_timeline(trace: dict[str, Any]) -> list[dict[str, Any]]:
    route = trace.get("route_info") if isinstance(trace.get("route_info"), dict) else {}
    final_result = trace.get("final_result") if isinstance(trace.get("final_result"), dict) else {}
    verifier = trace.get("verifier_result") if isinstance(trace.get("verifier_result"), dict) else {}

    model_calls = trace.get("model_calls") if isinstance(trace.get("model_calls"), list) else []
    tool_calls = trace.get("tool_calls") if isinstance(trace.get("tool_calls"), list) else []

    return [
        {"stage": "Router", "status": "ok" if route else "unavailable", "detail": route.get("problem_type", "unavailable")},
        {"stage": "Planner", "status": "ok" if any(c.get("stage") == "planner" for c in model_calls if isinstance(c, dict)) else "skipped", "detail": "model_call"},
        {"stage": "Solver", "status": "ok" if any(c.get("stage") == "solver" for c in model_calls if isinstance(c, dict)) else "skipped", "detail": "model_call"},
        {"stage": "Tool", "status": "ok" if tool_calls else "skipped", "detail": f"{len(tool_calls)} calls"},
        {"stage": "Verifier", "status": "ok" if verifier else "skipped", "detail": verifier.get("method", "unavailable")},
        {"stage": "Refiner", "status": "skipped", "detail": "not recorded"},
        {"stage": "Formatter", "status": "ok" if final_result else "unavailable", "detail": "final_result"},
        {"stage": "WeightedVoting", "status": "skipped", "detail": "not in main pipeline"},
        {"stage": "FinalResult", "status": "ok" if final_result else "unavailable", "detail": final_result.get("status", "unavailable")},
    ]


def summarize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    route = trace.get("route_info") if isinstance(trace.get("route_info"), dict) else {}
    final_result = trace.get("final_result") if isinstance(trace.get("final_result"), dict) else {}
    verification = final_result.get("verification") if isinstance(final_result.get("verification"), dict) else {}
    final_answer = final_result.get("final_answer") if isinstance(final_result.get("final_answer"), dict) else {}
    model_calls = trace.get("model_calls") if isinstance(trace.get("model_calls"), list) else []
    tool_calls = trace.get("tool_calls") if isinstance(trace.get("tool_calls"), list) else []

    q = str(trace.get("question") or "")
    preview = (q[:100] + "...") if len(q) > 100 else q
    risk_flags = []
    if isinstance(final_result.get("risk_flags"), list):
        risk_flags = [str(x) for x in final_result.get("risk_flags")]

    return {
        "question_id": str(trace.get("question_id") or "unknown"),
        "question_preview": preview,
        "domain": str(_pick(route, "domain", default="unknown")),
        "problem_type": str(_pick(route, "problem_type", default="unknown")),
        "status": str(final_result.get("status") or "unknown"),
        "final_answer": str(_pick(final_answer, "value", default="")),
        "verifier_passed": bool(verification.get("passed", False)),
        "verification_method": str(verification.get("method") or "unavailable"),
        "confidence": float(final_result.get("confidence", 0.0) or 0.0),
        "model_call_count": len(model_calls),
        "tool_call_count": len(tool_calls),
        "risk_flags": risk_flags,
        "latency_seconds": float(trace.get("latency_seconds", 0.0) or 0.0),
        "trace_ok": bool(trace),
    }


def render_replay_markdown(trace_or_summary: dict[str, Any]) -> str:
    if "question_preview" in trace_or_summary:
        summary = trace_or_summary
        timeline = []
    else:
        summary = summarize_trace(trace_or_summary)
        timeline = build_timeline(trace_or_summary)

    lines = [
        f"# Trace Replay: {summary['question_id']}",
        "",
        "## Summary",
        f"- status: {summary['status']}",
        f"- domain/problem_type: {summary['domain']} / {summary['problem_type']}",
        f"- final_answer: {summary['final_answer']}",
        f"- verifier: {summary['verifier_passed']} ({summary['verification_method']})",
        f"- confidence: {summary['confidence']}",
        f"- model_calls: {summary['model_call_count']}",
        f"- tool_calls: {summary['tool_call_count']}",
        f"- risk_flags: {', '.join(summary['risk_flags']) if summary['risk_flags'] else 'none'}",
        f"- latency_seconds: {summary['latency_seconds']}",
        "",
    ]
    if timeline:
        lines.extend(["## Timeline", "", "| Stage | Status | Detail |", "|---|---|---|"])
        for item in timeline:
            lines.append(f"| {item['stage']} | {item['status']} | {item['detail']} |")
    return "\n".join(lines) + "\n"
