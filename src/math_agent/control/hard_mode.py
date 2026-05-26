from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_ALLOWED_LEVELS = {"off", "light", "standard", "strict"}


@dataclass
class HardModePolicy:
    enabled: bool = False
    level: str = "off"
    candidate_budget: int = 1
    verifier_level: str = "basic"
    allow_tool_assist: bool = True
    allow_repair: bool = True
    require_trace: bool = False
    proof_guardian: bool = False
    shadow_eval_required: bool = False
    debugger_required: bool = False
    notes: list[str] = field(default_factory=list)


def infer_hard_mode_level(domain: str, difficulty: str, answer_type: str) -> str:
    domain_norm = (domain or "unknown").strip().lower()
    difficulty_norm = (difficulty or "unknown").strip().lower()
    answer_type_norm = (answer_type or "text").strip().lower()

    if answer_type_norm == "proof":
        return "strict" if difficulty_norm in {"very_hard", "olympiad"} else "standard"

    if difficulty_norm in {"very_hard", "olympiad"}:
        return "strict"
    if difficulty_norm == "hard":
        return "standard"

    if domain_norm in {"geometry", "number_theory", "combinatorics", "proof"}:
        return "standard"

    return "light"


def build_hard_mode_policy(
    enabled: bool = False,
    level: str = "off",
    domain: str = "unknown",
    difficulty: str = "unknown",
    answer_type: str = "text",
) -> HardModePolicy:
    selected = (level or "off").strip().lower()
    notes: list[str] = []

    if not enabled:
        selected = "off"
        notes.append("hard_mode_disabled")

    if selected not in _ALLOWED_LEVELS:
        notes.append(f"unknown_level:{selected}")
        selected = "off"

    suggested = infer_hard_mode_level(
        domain=domain, difficulty=difficulty, answer_type=answer_type
    )
    notes.append(f"suggested_level:{suggested}")

    policy = HardModePolicy(enabled=enabled, level=selected, notes=notes)

    if selected == "off":
        policy.candidate_budget = 1
        policy.verifier_level = "basic"
        policy.require_trace = False
        policy.proof_guardian = False
        policy.shadow_eval_required = False
        policy.debugger_required = False
    elif selected == "light":
        policy.candidate_budget = 2
        policy.verifier_level = "basic"
        policy.allow_tool_assist = True
        policy.allow_repair = True
    elif selected == "standard":
        policy.candidate_budget = 3
        policy.verifier_level = "strong"
        policy.allow_tool_assist = True
        policy.allow_repair = True
        policy.require_trace = True
        policy.proof_guardian = (answer_type or "").strip().lower() == "proof"
    elif selected == "strict":
        policy.candidate_budget = 5
        policy.verifier_level = "strict"
        policy.allow_tool_assist = True
        policy.allow_repair = True
        policy.require_trace = True
        policy.proof_guardian = True
        policy.shadow_eval_required = True
        policy.debugger_required = True

    return policy


def should_enable_proof_guardian(policy: HardModePolicy, answer_type: str) -> bool:
    answer_type_norm = (answer_type or "").strip().lower()
    return policy.proof_guardian and answer_type_norm == "proof"


def should_require_trace(policy: HardModePolicy) -> bool:
    return policy.require_trace


def validate_policy(policy: HardModePolicy) -> list[str]:
    errors: list[str] = []
    if policy.level not in _ALLOWED_LEVELS:
        errors.append(f"invalid level: {policy.level}")
    if policy.candidate_budget < 1:
        errors.append("candidate_budget must be >= 1")
    if policy.verifier_level not in {"basic", "strong", "strict"}:
        errors.append(f"invalid verifier_level: {policy.verifier_level}")
    if not policy.enabled and policy.level != "off":
        errors.append("disabled hard mode must use level 'off'")
    return errors


def policy_to_metadata(policy: HardModePolicy) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "level": policy.level,
        "candidate_budget": policy.candidate_budget,
        "verifier_level": policy.verifier_level,
        "allow_tool_assist": policy.allow_tool_assist,
        "allow_repair": policy.allow_repair,
        "require_trace": policy.require_trace,
        "proof_guardian": policy.proof_guardian,
        "shadow_eval_required": policy.shadow_eval_required,
        "debugger_required": policy.debugger_required,
        "notes": list(policy.notes),
    }
