import json
import subprocess
import sys

from math_agent.control.candidate_budget import build_candidate_budget_plan
from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.control.pipeline_hook import build_runtime_config
from math_agent.control.verifier_routing import build_verifier_routing_plan
from math_agent.control.weighted_voting_hook import (
    build_weighted_voting_runtime_plan,
    runtime_plan_to_metadata,
)
from math_agent.verification.verifier_scoring import (
    normalize_candidate_answer,
    score_candidate,
    score_candidates,
)
from math_agent.verification.weighted_voting import decision_to_metadata, weighted_vote


def test_scoring_and_voting_basics():
    assert normalize_candidate_answer(None) == ""
    assert normalize_candidate_answer("\\boxed{5}") in {"5", "\\boxed{5}"}
    assert score_candidate({"final_answer_value": ""}).passed is False
    assert score_candidate({"final_answer_value": "5"}).passed is True
    low = score_candidate(
        {"final_answer_value": "5", "risk_flags": ["dirty_boxed"]}
    ).final_score
    hi = score_candidate({"final_answer_value": "5"}).final_score
    assert low < hi
    scores = score_candidates(
        [{"final_answer_value": "5"}, {"final_answer_value": "6"}]
    )
    assert len(scores) == 2
    d = weighted_vote(
        [
            {"candidate_id": "a", "final_answer_value": "5"},
            {"candidate_id": "b", "final_answer_value": "6"},
        ],
        scores,
    )
    assert d.selected_candidate_id is not None
    assert json.dumps(decision_to_metadata(d))


def test_weighted_vote_fallback_and_tie():
    d = weighted_vote(
        [{"candidate_id": "a", "final_answer_value": ""}],
        [score_candidate({"candidate_id": "a", "final_answer_value": ""})],
    )
    assert d.fallback_used is True
    assert d.selected_answer != "42"


def test_runtime_plan_metadata():
    runtime = build_runtime_config(build_hard_mode_policy(enabled=True, level="strict"))
    budget = build_candidate_budget_plan(runtime)
    route = build_verifier_routing_plan(runtime, answer_type="proof")
    plan = build_weighted_voting_runtime_plan(
        runtime, budget, route, current_answer="5", answer_type="proof"
    )
    assert plan.verifier_level == "strict"
    assert json.dumps(runtime_plan_to_metadata(plan))


def test_cli_smoke_weighted_metadata(tmp_path):
    base = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "solve",
        "--question",
        "计算 2+3",
        "--enable-tools",
        "--mode",
        "fast",
    ]
    p = subprocess.run(
        base + ["--no-trace"], capture_output=True, text=True, check=True
    )
    assert "weighted_voting_plan" not in p.stdout
    trace = tmp_path / "tr"
    p2 = subprocess.run(
        base + ["--hard-mode", "--hard-mode-level", "light", "--trace-dir", str(trace)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert '"status":"success"' in p2.stdout
