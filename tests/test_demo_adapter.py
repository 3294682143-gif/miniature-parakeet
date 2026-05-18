from __future__ import annotations

from math_agent.harness.demo_adapter import (
    build_demo_budget_preview,
    build_demo_timeline,
    build_mock_voting_demo,
    load_demo_memory_summary,
    load_demo_skill_summary,
    result_to_display_dict,
    safe_get_risk_flags,
    safe_get_tool_calls,
)
from math_agent.schemas import FinalAnswer, ProblemParse, SolveResult, Verification


def _mock_result() -> SolveResult:
    return SolveResult(
        question_id="q1",
        domain="algebra",
        problem_type="calculation",
        problem_parse=ProblemParse(goal="2+3", givens=[], symbols=[]),
        final_answer=FinalAnswer(type="number", value="5", boxed="\\boxed{5}"),
        verification=Verification(method="numeric_check", passed=True, notes="ok"),
        didactic_hint="hint",
        confidence=0.8,
        status="success",
    )


def test_result_to_display_dict_ok() -> None:
    d = result_to_display_dict(_mock_result())
    assert d["final_answer"] == "5"
    assert d["verification_passed"] is True


def test_missing_fields_no_crash() -> None:
    d = result_to_display_dict({"status": "partial"})
    assert d["status"] == "partial"


def test_safe_get_tool_calls_empty() -> None:
    assert safe_get_tool_calls({}) == []


def test_safe_get_risk_flags_reads_verification_issues() -> None:
    flags = safe_get_risk_flags({"risk_flags": ["a"], "verification": {"issues": ["b"]}})
    assert flags == ["a", "b"]


def test_build_demo_timeline() -> None:
    timeline = build_demo_timeline(_mock_result())
    assert timeline[-1]["stage"] == "FinalResult"


def test_load_demo_skill_summary_missing_safe() -> None:
    out = load_demo_skill_summary("test")
    assert "skills" in out


def test_load_demo_memory_summary_missing_safe() -> None:
    out = load_demo_memory_summary()
    assert "summary" in out


def test_build_demo_budget_preview_read_only() -> None:
    out = build_demo_budget_preview("计算 2+3", route_info={"problem_type": "calculation"}, mode="full")
    assert "max_model_calls" in out


def test_build_mock_voting_demo_no_api() -> None:
    out = build_mock_voting_demo()
    assert "selected_answer" in out
