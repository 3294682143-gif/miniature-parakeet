import json
import subprocess
import sys

import pytest

from math_agent.schemas import (
    AgentStep,
    CandidateAnswer,
    FinalAnswer,
    ProblemParse,
    ProtocolVerifierResult,
    SolveResult,
    ToolCallRecord,
    Verification,
    WeightedVoteResult,
)


def test_agent_step_valid():
    step = AgentStep(step_id="s1", agent_name="planner", role="plan", status="success")
    assert step.status == "success"


def test_agent_step_invalid_status():
    with pytest.raises(Exception):
        AgentStep(step_id="s1", agent_name="planner", role="plan", status="bad")


def test_tool_call_record_valid_and_sanitized():
    rec = ToolCallRecord(
        tool_name="mock_tool",
        parameters={
            "api_key": "sk-123",
            "token": "abc",
            "Authorization": "Bearer xyz",
            "normal": 1,
            "nested": {"secret": "v", "ok": "yes"},
        },
        status="success",
    )
    assert rec.parameters["api_key"] == "[REDACTED]"
    assert rec.parameters["token"] == "[REDACTED]"
    assert rec.parameters["Authorization"] == "[REDACTED]"
    assert rec.parameters["nested"]["secret"] == "[REDACTED]"
    assert rec.parameters["normal"] == 1


def test_protocol_verifier_result_valid():
    item = ProtocolVerifierResult(
        passed=True,
        method="symbolic",
        confidence=0.8,
        suggested_action="stop",
    )
    assert item.passed is True


def test_protocol_verifier_result_invalid_confidence():
    with pytest.raises(Exception):
        ProtocolVerifierResult(
            passed=True,
            method="symbolic",
            confidence=1.1,
            suggested_action="stop",
        )


def test_protocol_verifier_result_invalid_method():
    with pytest.raises(Exception):
        ProtocolVerifierResult(
            passed=True,
            method="symbolic_check",  # old enum should not be accepted here
            confidence=0.5,
            suggested_action="stop",
        )


def test_candidate_answer_valid_and_bounds():
    item = CandidateAnswer(candidate_id="c1", source="solver", verifier_score=0.5, confidence=0.2, risk_score=0.1)
    assert item.candidate_id == "c1"
    with pytest.raises(Exception):
        CandidateAnswer(candidate_id="c2", source="solver", verifier_score=1.5)


def test_weighted_vote_result_valid():
    result = WeightedVoteResult(selected_candidate_id=None, confidence=0.0, issues=["no candidates"])
    assert result.selected_candidate_id is None


def test_protocol_objects_json_dumps():
    objects = [
        AgentStep(step_id="s1", agent_name="a", role="r", status="success"),
        ToolCallRecord(tool_name="t", status="skipped"),
        ProtocolVerifierResult(passed=False, method="none", confidence=0.0, suggested_action="fallback"),
        CandidateAnswer(candidate_id="c", source="x"),
        WeightedVoteResult(),
    ]
    for obj in objects:
        payload = obj.model_dump()
        json.dumps(payload)


def test_legacy_solveresult_still_validates():
    payload = {
        "question_id": "q1",
        "domain": "algebra",
        "problem_type": "equation",
        "problem_parse": {"goal": "x+1=2", "givens": ["x+1=2"], "symbols": ["x"]},
        "solution_plan": ["isolate x"],
        "visible_solution_steps": ["x=1"],
        "tool_trace": [{"tool": "none", "purpose": "n/a", "status": "skipped", "summary": "n/a"}],
        "final_answer": {"type": "number", "value": "1", "boxed": "\\boxed{1}"},
        "verification": {"method": "none", "passed": True, "notes": "ok"},
        "didactic_hint": "hint",
        "confidence": 0.7,
        "status": "success",
    }
    obj = SolveResult.model_validate(payload)
    assert isinstance(obj.problem_parse, ProblemParse)
    assert isinstance(obj.final_answer, FinalAnswer)
    assert isinstance(obj.verification, Verification)


def test_cli_mock_solve_and_batch_smoke(tmp_path):
    solve = subprocess.run(
        [sys.executable, "-m", "math_agent.cli", "solve", "--question", "1+1=?", "--question-id", "proto_1", "--no-trace"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "proto_1" in solve.stdout

    inp = tmp_path / "in.jsonl"
    outp = tmp_path / "out.jsonl"
    inp.write_text('{"question_id":"b1","question":"1+2=?"}\n', encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "math_agent.cli", "batch", "--input", str(inp), "--output", str(outp), "--no-trace"],
        check=True,
    )
    assert outp.exists()
