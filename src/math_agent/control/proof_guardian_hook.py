from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from math_agent.proof import build_proof_guardian_decision, score_proof_candidate

from .pipeline_hook import HardModeRuntimeConfig
from .verifier_routing import VerifierRoutingPlan


@dataclass
class ProofGuardianRuntimePlan:
    enabled: bool
    mode: str
    answer_type: str
    proof_guardian_required: bool
    allow_partial: bool
    decision: dict[str, Any] | None
    notes: list[str] = field(default_factory=list)


def build_proof_guardian_runtime_plan(
    hard_mode_runtime: HardModeRuntimeConfig | None,
    verifier_routing_plan: VerifierRoutingPlan | None,
    current_answer: Any,
    answer_type: str = "text",
) -> ProofGuardianRuntimePlan:
    if hard_mode_runtime is None or not hard_mode_runtime.enabled:
        return ProofGuardianRuntimePlan(
            False, "disabled", answer_type, False, False, None, ["hard_mode_disabled"]
        )
    required = bool(
        (verifier_routing_plan and verifier_routing_plan.proof_guardian)
        or hard_mode_runtime.proof_guardian
        or answer_type == "proof"
    )
    if not required:
        return ProofGuardianRuntimePlan(
            False,
            "not_proof",
            answer_type,
            False,
            False,
            None,
            ["proof_guardian_not_required"],
        )
    score = score_proof_candidate(current_answer, answer_type="proof")
    decision = build_proof_guardian_decision([score], allow_partial=False)
    return ProofGuardianRuntimePlan(
        True,
        "proof_guardian_preview",
        answer_type,
        True,
        False,
        asdict(decision),
        ["preview_only", "no_final_answer_override"],
    )


def proof_guardian_runtime_plan_to_metadata(
    plan: ProofGuardianRuntimePlan,
) -> dict[str, Any]:
    return asdict(plan)
