from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .hard_mode import HardModePolicy, should_enable_proof_guardian


@dataclass
class HardModeRuntimeConfig:
    enabled: bool
    level: str
    candidate_budget: int
    effective_candidate_budget: int
    verifier_level: str
    require_trace: bool
    trace_allowed: bool
    proof_guardian: bool
    allow_repair: bool
    shadow_eval_required: bool
    debugger_required: bool
    effect: str
    notes: list[str] = field(default_factory=list)


def apply_policy_notes(
    policy: HardModePolicy,
    no_trace: bool,
    answer_type: str,
    max_candidate_budget: int,
) -> list[str]:
    notes = list(policy.notes)
    if policy.candidate_budget > max_candidate_budget:
        notes.append("candidate_budget_capped_for_controlled_hook")
    if policy.require_trace and no_trace:
        notes.append("trace_required_by_policy_but_no_trace_flag_wins")
    if should_enable_proof_guardian(policy, answer_type):
        notes.append("proof_guardian_runtime_hook_enabled")
    return notes


def build_runtime_config(
    policy: HardModePolicy | None,
    no_trace: bool = False,
    answer_type: str = "text",
    max_candidate_budget: int = 3,
) -> HardModeRuntimeConfig:
    if policy is None or not policy.enabled:
        return HardModeRuntimeConfig(
            enabled=False,
            level="off",
            candidate_budget=1,
            effective_candidate_budget=1,
            verifier_level="basic",
            require_trace=False,
            trace_allowed=not no_trace,
            proof_guardian=False,
            allow_repair=True,
            shadow_eval_required=False,
            debugger_required=False,
            effect="disabled",
            notes=["hard_mode_disabled"],
        )

    effective_budget = min(policy.candidate_budget, max_candidate_budget)
    return HardModeRuntimeConfig(
        enabled=policy.enabled,
        level=policy.level,
        candidate_budget=policy.candidate_budget,
        effective_candidate_budget=max(1, effective_budget),
        verifier_level=policy.verifier_level,
        require_trace=policy.require_trace,
        trace_allowed=not no_trace,
        proof_guardian=should_enable_proof_guardian(policy, answer_type),
        allow_repair=policy.allow_repair,
        shadow_eval_required=policy.shadow_eval_required,
        debugger_required=policy.debugger_required,
        effect="controlled_runtime_hook",
        notes=apply_policy_notes(policy, no_trace, answer_type, max_candidate_budget),
    )


def runtime_config_to_metadata(config: HardModeRuntimeConfig) -> dict[str, Any]:
    return asdict(config)
