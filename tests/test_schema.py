import json

import pytest
from pydantic import ValidationError

from math_agent.schemas import SolveResult, make_failure_result, validate_result_dict


def _valid_payload() -> dict:
    return {
        "question_id": "q1",
        "domain": "algebra",
        "problem_type": "equation",
        "problem_parse": {"goal": "solve x+1=2", "givens": ["x+1=2"], "symbols": ["x"]},
        "solution_plan": ["isolate x"],
        "visible_solution_steps": ["x=1"],
        "tool_trace": [{"tool": "none", "purpose": "mental", "status": "skipped", "summary": "not needed"}],
        "final_answer": {"type": "number", "value": "1", "boxed": "1"},
        "verification": {"method": "substitution", "passed": True, "notes": "checks out"},
        "didactic_hint": "Move constants across equation.",
        "confidence": 0.8,
        "status": "success",
        "error": None,
    }


def test_valid_solve_result_schema():
    obj = validate_result_dict(_valid_payload())
    assert isinstance(obj, SolveResult)


def test_confidence_out_of_range_fails():
    bad = _valid_payload()
    bad["confidence"] = 1.2
    with pytest.raises(ValidationError):
        validate_result_dict(bad)


def test_status_invalid_fails():
    bad = _valid_payload()
    bad["status"] = "done"
    with pytest.raises(ValidationError):
        validate_result_dict(bad)


def test_make_failure_result_json_serializable():
    result = make_failure_result("qf", "1/0=?", "division by zero")
    dumped = result.model_dump(mode="json")
    json.dumps(dumped)
    assert dumped["status"] == "fail"
