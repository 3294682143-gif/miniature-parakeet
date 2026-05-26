from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .candidate_budget import CandidateBudgetPlan
from .pipeline_hook import HardModeRuntimeConfig
from .verifier_routing import VerifierRoutingPlan


@dataclass
class WeightedVotingRuntimePlan:
    enabled: bool
    mode: str
    candidate_count: int
    verifier_level: str
    allow_answer_override: bool
    decision: dict[str, Any] | None
    notes: list[str] = field(default_factory=list)


def build_weighted_voting_runtime_plan(
    hard_mode_runtime: HardModeRuntimeConfig | None,
    candidate_budget_plan: CandidateBudgetPlan | None,
    verifier_routing_plan: VerifierRoutingPlan | None,
    current_answer: Any,
    answer_type: str = "text",
) -> WeightedVotingRuntimePlan:
    if hard_mode_runtime is None or not hard_mode_runtime.enabled:
        return WeightedVotingRuntimePlan(
            False, "disabled", 1, "basic", False, None, ["hard_mode_disabled"]
        )
    budget = (
        1 if candidate_budget_plan is None else candidate_budget_plan.effective_budget
    )
    if budget <= 1:
        return WeightedVotingRuntimePlan(
            False,
            "single_candidate",
            1,
            (
                verifier_routing_plan.verifier_level
                if verifier_routing_plan
                else hard_mode_runtime.verifier_level
            ),
            False,
            None,
            ["single_candidate_fallback"],
        )
    return WeightedVotingRuntimePlan(
        True,
        "controlled_weighted_voting_preview",
        budget,
        (
            verifier_routing_plan.verifier_level
            if verifier_routing_plan
            else hard_mode_runtime.verifier_level
        ),
        False,
        None,
        ["preview_only"],
    )


def runtime_plan_to_metadata(plan: WeightedVotingRuntimePlan) -> dict[str, Any]:
    return asdict(plan)
