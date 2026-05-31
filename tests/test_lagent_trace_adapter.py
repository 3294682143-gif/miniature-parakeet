from __future__ import annotations

from math_agent.harness.lagent_trace_adapter import (
    lagent_alignment_evidence_table,
    trace_to_lagent_messages,
)


def test_trace_to_lagent_messages_redacts_sensitive_metadata() -> None:
    messages = trace_to_lagent_messages(
        {
            "question_id": "q1",
            "question": "Compute 2+3.",
            "route_info": {
                "domain": "Algebra",
                "problem_type": "calculation",
                "recommended_solver": "program",
            },
            "model_calls": [
                {
                    "stage": "solver",
                    "status": "ok",
                    "model": "intern-s1",
                    "authorization": "Bearer SECRET",
                }
            ],
            "tool_calls": [{"tool": "sympy", "status": "success", "summary": "5"}],
            "final_result": {
                "status": "success",
                "final_answer": {"value": "5", "boxed": "\\boxed{5}"},
            },
        }
    )
    assert [message["sender"] for message in messages] == [
        "question",
        "router",
        "solver",
        "sympy",
        "formatter",
    ]
    rendered = str(messages)
    assert "SECRET" not in rendered
    assert "[REDACTED]" in rendered


def test_lagent_alignment_evidence_table_mentions_core_stages() -> None:
    rows = lagent_alignment_evidence_table()
    stages = {row["project_stage"] for row in rows}
    assert {"Planner", "Solver", "Verifier", "Tool Observation"}.issubset(stages)
    assert all(row["lagent_concept"] for row in rows)
    assert all(row["trace_source"] for row in rows)
