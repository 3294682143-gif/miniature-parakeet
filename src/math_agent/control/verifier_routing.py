from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .pipeline_hook import HardModeRuntimeConfig


@dataclass
class VerifierRoutingPlan:
    enabled: bool
    verifier_level: str
    route: str
    require_strict_checks: bool
    allow_repair: bool
    proof_guardian: bool
    notes: list[str] = field(default_factory=list)


def build_verifier_routing_plan(
    runtime_config: HardModeRuntimeConfig | None,
    answer_type: str = "text",
) -> VerifierRoutingPlan:
    notes: list[str] = []
    answer_type_norm = (answer_type or "text").strip().lower()

    if runtime_config is None or not runtime_config.enabled:
        return VerifierRoutingPlan(
            enabled=False,
            verifier_level="basic",
            route="default",
            require_strict_checks=False,
            allow_repair=True,
            proof_guardian=False,
            notes=notes,
        )

    verifier_level = (runtime_config.verifier_level or "basic").strip().lower()
    route = "basic_verifier"
    require_strict_checks = False

    if verifier_level == "strong":
        route = "strong_verifier_preview"
        require_strict_checks = True
    elif verifier_level == "strict":
        route = "strict_verifier_preview"
        require_strict_checks = True
        notes.append("strict_verifier_preview_only")

    proof_guardian = answer_type_norm == "proof" or runtime_config.proof_guardian
    if proof_guardian:
        notes.append("proof_guardian_route_preview")

    return VerifierRoutingPlan(
        enabled=True,
        verifier_level=verifier_level,
        route=route,
        require_strict_checks=require_strict_checks,
        allow_repair=True,
        proof_guardian=proof_guardian,
        notes=notes,
    )


def verifier_routing_plan_to_metadata(plan: VerifierRoutingPlan) -> dict[str, Any]:
    return asdict(plan)
