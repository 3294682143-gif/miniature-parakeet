import json
import subprocess
import sys
from dataclasses import replace

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
    assert score_candidate({"final_answer_value": "5"}).passed is False
    assert (
        score_candidate({"final_answer_value": "5", "verification_passed": True}).passed
        is True
    )
    low = score_candidate(
        {"final_answer_value": "5", "risk_flags": ["dirty_boxed"]}
    ).final_score
    hi = score_candidate({"final_answer_value": "5"}).final_score
    assert low < hi
    candidates = [
        {
            "candidate_id": "a",
            "final_answer_value": "5",
            "verification_passed": True,
        },
        {
            "candidate_id": "b",
            "final_answer_value": "6",
            "verification_passed": True,
        },
    ]
    scores = score_candidates(candidates)
    assert len(scores) == 2
    d = weighted_vote(candidates, scores)
    assert d.selected_candidate_id is not None
    assert json.dumps(decision_to_metadata(d))


def test_weighted_vote_fallback_and_tie():
    d = weighted_vote(
        [{"candidate_id": "a", "final_answer_value": ""}],
        [score_candidate({"candidate_id": "a", "final_answer_value": ""})],
    )
    assert d.fallback_used is True
    assert d.selected_answer != "42"


def test_weighted_vote_aligns_scores_by_candidate_id_not_list_order():
    candidates = [
        {
            "candidate_id": "a",
            "final_answer_value": "5",
            "verification_passed": True,
        },
        {
            "candidate_id": "b",
            "final_answer_value": "6",
            "verification_passed": True,
        },
    ]
    scores = score_candidates(candidates, expected_answer="5")

    decision = weighted_vote(candidates, list(reversed(scores)))

    assert decision.selected_candidate_id == "a"
    assert decision.selected_answer == "5"


def test_weighted_vote_fails_closed_on_alignment_errors():
    candidates = [
        {
            "candidate_id": "a",
            "final_answer_value": "5",
            "verification_passed": True,
        },
        {
            "candidate_id": "b",
            "final_answer_value": "6",
            "verification_passed": True,
        },
    ]
    scores = score_candidates(candidates)

    missing_score = weighted_vote(candidates, scores[:1])
    duplicate_candidates = weighted_vote(
        [candidates[0], candidates[0]], [scores[0], scores[0]]
    )

    for decision in (missing_score, duplicate_candidates):
        assert decision.selected_candidate_id is None
        assert "candidate_score_alignment_error" in decision.risk_flags


def test_failed_verifier_score_cannot_win_and_risks_propagate():
    candidates = [
        {
            "candidate_id": "failed",
            "final_answer_value": "5",
            "risk_flags": ["tool_failed"],
        },
        {
            "candidate_id": "passed",
            "final_answer_value": "6",
            "verification_passed": True,
        },
    ]
    scores = score_candidates(candidates)
    scores[0] = replace(scores[0], final_score=1.0, passed=False)

    decision = weighted_vote(candidates, scores)

    assert decision.selected_candidate_id == "passed"
    assert "tool_failed" not in decision.risk_flags

    risky_decision = weighted_vote(candidates[:1], [replace(scores[0], passed=True)])
    assert "tool_failed" in risky_decision.risk_flags


def test_failed_tool_signal_lowers_tool_score():
    successful = score_candidate(
        {
            "final_answer_value": "5",
            "metadata": {"tool_used": True, "tool_status": "success"},
        }
    )
    failed = score_candidate(
        {
            "final_answer_value": "5",
            "metadata": {"tool_used": True, "tool_status": "fail"},
        }
    )

    assert failed.tool_score < successful.tool_score
    assert "tool_failed" in failed.risk_flags


def test_explicit_verifier_failure_is_respected_at_every_level():
    candidate = {
        "final_answer_value": "5",
        "verifier_score": 0.0,
        "verification_passed": False,
    }

    for level in ("basic", "strong", "strict"):
        score = score_candidate(candidate, verifier_level=level)
        assert score.passed is False
        assert "verifier_failed" in score.risk_flags


def test_verifier_level_changes_acceptance_threshold():
    candidate = {
        "final_answer_value": "5",
        "risk_flags": ["dirty_boxed"],
        "verification_passed": True,
    }

    basic = score_candidate(candidate, verifier_level="basic")
    strict = score_candidate(candidate, verifier_level="strict")

    assert basic.passed is True
    assert strict.passed is False
    assert basic.final_score == strict.final_score


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


def test_proof_rubric_scoring_effects():
    good = score_candidate(
        {"final_answer_value": "设a，因为a=2m，所以成立，故命题成立"},
        answer_type="proof",
    )
    bad = score_candidate(
        {"final_answer_value": "矛盾 contradiction"}, answer_type="proof"
    )
    assert good.proof_score != 0.5
    assert bad.final_score < good.final_score
    assert any("proof_rubric" in r for r in bad.reasons)
    normal = score_candidate({"final_answer_value": "5"}, answer_type="number")
    assert not any("proof_rubric" in r for r in normal.reasons)
