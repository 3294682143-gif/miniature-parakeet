from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from math_agent.agents.proof_guardian import detect_proof_problem

_DEFAULT_CONFIG: dict[str, Any] = {
    "easy": {"max_candidates": 1, "max_refine_rounds": 0, "tool_first": True, "max_model_calls": 1, "timeout_seconds": 30},
    "standard": {"max_candidates": 2, "max_refine_rounds": 1, "tool_first": True, "max_model_calls": 3, "timeout_seconds": 60},
    "hard": {"max_candidates": 5, "max_refine_rounds": 2, "tool_first": True, "max_model_calls": 7, "timeout_seconds": 120},
    "domain_overrides": {
        "calculation": {"max_candidates": 1, "tool_first": True},
        "equation": {"max_candidates": 1, "tool_first": True},
        "matrix": {"max_candidates": 1, "tool_first": True},
        "probability": {"max_candidates": 2, "tool_first": True},
        "proof": {"max_candidates": 2, "max_refine_rounds": 1, "tool_first": False},
        "topology": {"max_candidates": 2, "max_refine_rounds": 1, "tool_first": False},
        "real_analysis": {"max_candidates": 2, "max_refine_rounds": 1, "tool_first": False},
        "optimization": {"max_candidates": 3, "tool_first": True},
        "unknown": {"max_candidates": 2, "tool_first": True},
    },
}

_PROOF_LIKE = {"proof", "topology", "real_analysis"}


@dataclass
class BudgetDecision:
    budget_name: str
    mode: str
    domain: str
    problem_type: str
    max_candidates: int
    max_refine_rounds: int
    max_model_calls: int
    timeout_seconds: int
    tool_first: bool
    enable_voting: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.max_candidates = max(1, int(self.max_candidates))
        self.max_refine_rounds = max(0, int(self.max_refine_rounds))
        self.max_model_calls = max(0, int(self.max_model_calls))
        self.timeout_seconds = max(0, int(self.timeout_seconds))


def load_budget_config(path: str = "configs/budgets.yaml") -> dict[str, Any]:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            merged = dict(_DEFAULT_CONFIG)
            merged.update({k: v for k, v in raw.items() if k != "domain_overrides"})
            overrides = dict(_DEFAULT_CONFIG["domain_overrides"])
            if isinstance(raw.get("domain_overrides"), dict):
                overrides.update(raw["domain_overrides"])
            merged["domain_overrides"] = overrides
            return merged
    except Exception:
        pass
    return _DEFAULT_CONFIG


def infer_domain(route_info: Any = None, question: str | None = None) -> str:
    info = route_info if isinstance(route_info, dict) else getattr(route_info, "__dict__", {}) or {}
    domain = str(info.get("domain", "") or "").strip().lower()
    if domain:
        return domain
    ptype = str(info.get("problem_type", "") or "").strip().lower()
    if ptype:
        return ptype

    q = (question or "").lower()
    if detect_proof_problem(question or "", info):
        return "proof"
    if any(k in q for k in ["matrix", "矩阵", "determinant", "eigen"]):
        return "matrix"
    if any(k in q for k in ["equation", "方程", "solve", "解方程", "="]):
        return "equation"
    if any(k in q for k in ["probability", "概率", "expectation", "variance"]):
        return "probability"
    if any(k in q for k in ["optimiz", "最优", "maximize", "minimize"]):
        return "optimization"
    if any(k in q for k in ["compute", "calculation", "计算", "求值"]):
        return "calculation"
    return "unknown"


def clamp_candidate_count(requested_count: int | None, budget_name: str, domain: str, config: dict[str, Any]) -> int:
    budget_limits = {"easy": 1, "standard": 2, "hard": 5}
    budget_limit = budget_limits.get(budget_name, 2)
    budget_cfg = config.get(budget_name, {}) if isinstance(config, dict) else {}
    budget_limit = min(budget_limit, int(budget_cfg.get("max_candidates", budget_limit)))

    domain_limit = int(config.get("domain_overrides", {}).get(domain, {}).get("max_candidates", budget_limit))
    if domain in _PROOF_LIKE:
        domain_limit = min(domain_limit, 2)
    if domain in {"calculation", "equation", "matrix"}:
        domain_limit = min(domain_limit, 1)

    limit = max(1, min(budget_limit, domain_limit))
    if not isinstance(requested_count, int) or requested_count <= 0:
        return 1
    return max(1, min(requested_count, limit))


def should_tool_first(domain: str, mode: str, config: dict[str, Any]) -> bool:
    if mode == "tool-first":
        return True
    if mode == "fast":
        return True

    domain_cfg = config.get("domain_overrides", {}).get(domain, {})
    if "tool_first" in domain_cfg:
        return bool(domain_cfg["tool_first"])
    return True


def allocate_budget(
    route_info: Any = None,
    question: str | None = None,
    mode: str = "full",
    requested_budget: str = "standard",
    requested_candidate_count: int | None = None,
    request_voting: bool = False,
    config_path: str = "configs/budgets.yaml",
) -> BudgetDecision:
    config = load_budget_config(config_path)
    warnings: list[str] = []
    reason_parts: list[str] = []

    valid_budgets = {"easy", "standard", "hard"}
    budget_name = requested_budget if requested_budget in valid_budgets else "standard"
    if requested_budget not in valid_budgets:
        warnings.append(f"invalid requested_budget={requested_budget}, fallback to standard")

    if mode == "fast":
        budget_name = "easy"
    elif mode in {"full", "tool-first"} and requested_budget not in valid_budgets:
        budget_name = "standard"

    base = dict(config.get(budget_name, _DEFAULT_CONFIG[budget_name]))
    domain = infer_domain(route_info=route_info, question=question)
    problem_type = ""
    if isinstance(route_info, dict):
        problem_type = str(route_info.get("problem_type", "") or "")

    domain_override = config.get("domain_overrides", {}).get(domain, {})
    for key in ["max_candidates", "max_refine_rounds", "tool_first", "max_model_calls", "timeout_seconds"]:
        if key in domain_override:
            base[key] = domain_override[key]

    clamped = clamp_candidate_count(requested_candidate_count, budget_name, domain, config)
    if requested_candidate_count is None:
        base_candidates = int(base.get("max_candidates", 1))
        base["max_candidates"] = max(1, min(base_candidates, clamped))
    else:
        base["max_candidates"] = clamped
    if requested_candidate_count != base["max_candidates"]:
        warnings.append(f"candidate_count clamped to {base['max_candidates']}")
        reason_parts.append("candidate clamped by budget/domain limits")

    tool_first = should_tool_first(domain, mode, config)
    if mode == "tool-first":
        tool_first = True

    enable_voting = bool(request_voting and base["max_candidates"] >= 2)
    if request_voting and not enable_voting:
        warnings.append("voting requested but disabled due to candidate budget")

    if not reason_parts:
        reason_parts.append("budget allocated safely")

    return BudgetDecision(
        budget_name=budget_name,
        mode=mode,
        domain=domain,
        problem_type=problem_type,
        max_candidates=int(base.get("max_candidates", 1)),
        max_refine_rounds=int(base.get("max_refine_rounds", 0)),
        max_model_calls=int(base.get("max_model_calls", 0)),
        timeout_seconds=int(base.get("timeout_seconds", 0)),
        tool_first=tool_first,
        enable_voting=enable_voting,
        reason="; ".join(reason_parts),
        warnings=warnings,
    )


def explain_budget_decision(decision: BudgetDecision) -> str:
    return (
        f"budget={decision.budget_name}, mode={decision.mode}, domain={decision.domain}, "
        f"candidates={decision.max_candidates}, refine={decision.max_refine_rounds}, "
        f"calls={decision.max_model_calls}, tool_first={decision.tool_first}, voting={decision.enable_voting}"
    )


def budget_decision_to_dict(decision: BudgetDecision) -> dict[str, Any]:
    return asdict(decision)
