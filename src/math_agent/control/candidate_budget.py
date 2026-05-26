from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .pipeline_hook import HardModeRuntimeConfig


@dataclass
class CandidateBudgetPlan:
    enabled: bool
    requested_budget: int
    effective_budget: int
    max_budget: int
    strategy: str
    deterministic: bool
    notes: list[str] = field(default_factory=list)


def build_candidate_budget_plan(
    runtime_config: HardModeRuntimeConfig | None,
    max_budget: int = 3,
) -> CandidateBudgetPlan:
    if runtime_config is None or not runtime_config.enabled:
        return CandidateBudgetPlan(
            enabled=False,
            requested_budget=1,
            effective_budget=1,
            max_budget=max_budget,
            strategy="single",
            deterministic=True,
            notes=[],
        )

    level = (runtime_config.level or "off").strip().lower()
    requested_budget = 1
    strategy = "single"
    notes: list[str] = []

    if level == "light":
        requested_budget = 2
        strategy = "budget_preview"
    elif level == "standard":
        requested_budget = 3
        strategy = "budget_preview"
    elif level == "strict":
        requested_budget = 5
        strategy = "capped_budget_preview"
    else:
        requested_budget = max(1, runtime_config.effective_candidate_budget)

    effective_budget = min(requested_budget, max_budget)
    if level == "strict" and requested_budget > effective_budget:
        notes.append("candidate_budget_capped_for_controlled_candidate_hook")

    return CandidateBudgetPlan(
        enabled=True,
        requested_budget=requested_budget,
        effective_budget=max(1, effective_budget),
        max_budget=max_budget,
        strategy=strategy,
        deterministic=True,
        notes=notes,
    )


def candidate_budget_plan_to_metadata(plan: CandidateBudgetPlan) -> dict[str, Any]:
    return asdict(plan)
