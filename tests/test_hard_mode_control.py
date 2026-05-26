from __future__ import annotations

from math_agent.control.hard_mode import (
    HardModePolicy,
    build_hard_mode_policy,
    infer_hard_mode_level,
    should_enable_proof_guardian,
    should_require_trace,
    validate_policy,
)


def test_default_policy_is_disabled_off() -> None:
    policy = build_hard_mode_policy()
    assert policy.enabled is False
    assert policy.level == "off"


def test_policy_level_budgets() -> None:
    assert build_hard_mode_policy(enabled=True, level="off").candidate_budget == 1
    assert build_hard_mode_policy(enabled=True, level="light").candidate_budget == 2
    assert build_hard_mode_policy(enabled=True, level="standard").candidate_budget >= 3
    assert build_hard_mode_policy(enabled=True, level="strict").candidate_budget >= 5


def test_strict_policy_flags() -> None:
    policy = build_hard_mode_policy(enabled=True, level="strict")
    assert policy.require_trace is True
    assert policy.shadow_eval_required is True
    assert policy.debugger_required is True


def test_proof_guardian_for_proof_answer_type() -> None:
    standard = build_hard_mode_policy(
        enabled=True,
        level="standard",
        answer_type="proof",
    )
    strict = build_hard_mode_policy(enabled=True, level="strict", answer_type="proof")
    assert should_enable_proof_guardian(standard, "proof") is True
    assert should_enable_proof_guardian(strict, "proof") is True


def test_infer_level_hard_and_proof() -> None:
    hard_level = infer_hard_mode_level("algebra", "hard", "text")
    proof_level = infer_hard_mode_level("algebra", "normal", "proof")
    assert hard_level in {"standard", "strict"}
    assert proof_level in {"standard", "strict"}


def test_validate_policy_rejects_invalid_values() -> None:
    bad_level = HardModePolicy(enabled=True, level="unknown")
    bad_level_errors = validate_policy(bad_level)
    assert any("invalid level" in err for err in bad_level_errors)

    bad_budget = HardModePolicy(enabled=True, level="off", candidate_budget=0)
    bad_budget_errors = validate_policy(bad_budget)
    assert any("candidate_budget" in err for err in bad_budget_errors)


def test_default_policy_has_no_real_env_or_outputs_side_effects() -> None:
    policy = build_hard_mode_policy()
    dumped = repr(policy) + " " + " ".join(policy.notes)
    assert "--real" not in dumped
    assert ".env" not in dumped
    assert "official_results.jsonl" not in dumped


def test_should_require_trace_helper() -> None:
    assert (
        should_require_trace(build_hard_mode_policy(enabled=True, level="strict"))
        is True
    )
    assert (
        should_require_trace(build_hard_mode_policy(enabled=True, level="off")) is False
    )
