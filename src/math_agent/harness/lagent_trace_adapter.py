from __future__ import annotations

from typing import Any

from math_agent.schemas import AgentStep, ToolCallRecord, sanitize_protocol_metadata

LAGENT_ALIGNMENT_EVIDENCE: tuple[dict[str, str], ...] = (
    {
        "project_stage": "Planner",
        "lagent_concept": "Agent message",
        "trace_source": "model_calls[stage=planner]",
        "review_evidence": "planning intent is exported as a sanitized assistant message",
    },
    {
        "project_stage": "Solver",
        "lagent_concept": "Agent message",
        "trace_source": "model_calls[stage=solver]",
        "review_evidence": "solver reasoning/call metadata is exported without secrets",
    },
    {
        "project_stage": "Verifier",
        "lagent_concept": "Agent message / critic",
        "trace_source": "model_calls[stage=verifier], final_result.verification",
        "review_evidence": "verification status and method are visible in the final formatter message",
    },
    {
        "project_stage": "Tool Observation",
        "lagent_concept": "Action observation",
        "trace_source": "tool_calls[]",
        "review_evidence": "tool name, status, parameters, latency, and summary map to tool messages",
    },
)


def _short_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def agent_step_to_lagent_message(step: AgentStep) -> dict[str, Any]:
    return sanitize_protocol_metadata(
        {
            "role": "assistant",
            "sender": step.agent_name,
            "content": step.output_summary or step.input_summary,
            "formatted": {
                "step_id": step.step_id,
                "role": step.role,
                "status": step.status,
                "risk_flags": list(step.risk_flags),
                "metadata": dict(step.metadata),
            },
        }
    )


def tool_call_to_lagent_message(
    record: ToolCallRecord | dict[str, Any],
) -> dict[str, Any]:
    payload = (
        record.model_dump()
        if isinstance(record, ToolCallRecord)
        else dict(record or {})
    )
    return sanitize_protocol_metadata(
        {
            "role": "tool",
            "sender": str(payload.get("tool_name") or payload.get("tool") or "tool"),
            "content": _short_text(
                payload.get("result_summary") or payload.get("summary") or ""
            ),
            "formatted": {
                "status": payload.get("status", "unknown"),
                "parameters": payload.get("parameters", {}),
                "latency_seconds": payload.get("latency_seconds"),
                "error": payload.get("error"),
            },
        }
    )


def trace_to_lagent_messages(trace: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    question = trace.get("question")
    if question:
        messages.append(
            {
                "role": "user",
                "sender": "question",
                "content": _short_text(question),
                "formatted": {"question_id": trace.get("question_id", "unknown")},
            }
        )

    route_info = trace.get("route_info")
    if isinstance(route_info, dict) and route_info:
        messages.append(
            sanitize_protocol_metadata(
                {
                    "role": "assistant",
                    "sender": "router",
                    "content": _short_text(route_info),
                    "formatted": {
                        "domain": route_info.get("domain"),
                        "problem_type": route_info.get("problem_type"),
                        "recommended_solver": route_info.get("recommended_solver"),
                    },
                }
            )
        )

    for call in trace.get("model_calls", []) or []:
        if not isinstance(call, dict):
            continue
        messages.append(
            sanitize_protocol_metadata(
                {
                    "role": "assistant",
                    "sender": str(call.get("stage", "model")),
                    "content": (
                        f"model={call.get('model', 'unknown')} "
                        f"status={call.get('status', 'unknown')}"
                    ),
                    "formatted": dict(call),
                }
            )
        )

    for call in trace.get("tool_calls", []) or []:
        if isinstance(call, dict):
            messages.append(tool_call_to_lagent_message(call))

    final_result = trace.get("final_result")
    if isinstance(final_result, dict):
        final_answer = final_result.get("final_answer")
        value = ""
        if isinstance(final_answer, dict):
            value = str(final_answer.get("value", ""))
        messages.append(
            sanitize_protocol_metadata(
                {
                    "role": "assistant",
                    "sender": "formatter",
                    "content": _short_text(value),
                    "formatted": {
                        "status": final_result.get("status"),
                        "verification": final_result.get("verification"),
                        "final_answer": final_answer,
                    },
                }
            )
        )
    return messages


def lagent_alignment_evidence_table() -> list[dict[str, str]]:
    return [dict(row) for row in LAGENT_ALIGNMENT_EVIDENCE]
