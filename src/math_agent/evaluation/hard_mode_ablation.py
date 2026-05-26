from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.debugger.failure_attribution import (
    build_debugger_report,
    load_shadow_results,
    write_debugger_outputs,
)
from math_agent.evaluation.report import write_markdown_report
from math_agent.evaluation.shadow_eval import (
    load_cases,
    run_shadow_eval,
    summarize_results,
    write_jsonl,
    write_summary,
)


@dataclass
class HardModeAblationConfig:
    levels: list[str]
    limit: int
    input_path: str | None
    include_debugger: bool
    out_dir: str
    mock: bool = True


@dataclass
class HardModeRunResult:
    level: str
    policy: dict[str, Any]
    result_count: int
    summary: dict[str, Any]
    debugger_summary: dict[str, Any] | None
    output_dir: str


@dataclass
class HardModeAblationReport:
    levels: list[str]
    total_cases: int
    runs: list[HardModeRunResult]
    comparison: dict[str, Any]
    recommendation: list[str]
    official_warning: str


def build_ablation_config(**kwargs: Any) -> HardModeAblationConfig:
    return HardModeAblationConfig(
        levels=kwargs.get("levels") or ["off", "light", "standard", "strict"],
        limit=max(0, int(kwargs.get("limit", 5))),
        input_path=kwargs.get("input_path"),
        include_debugger=bool(kwargs.get("include_debugger", True)),
        out_dir=str(kwargs.get("out_dir", "outputs/hard_mode_ablation")),
        mock=bool(kwargs.get("mock", True)),
    )


def run_single_level_ablation(
    level: str, cases: list[Any], out_dir: Path | str, include_debugger: bool
) -> HardModeRunResult:
    level_out = Path(out_dir)
    level_out.mkdir(parents=True, exist_ok=True)
    policy = asdict(build_hard_mode_policy(enabled=True, level=level))
    try:
        results = run_shadow_eval(
            cases, options={"mock": True, "ablation_level": level}
        )
        summary_obj = summarize_results(results)
        write_jsonl(results, level_out / "shadow_results.jsonl")
        write_summary(summary_obj, level_out / "shadow_summary.json")
        write_markdown_report(summary_obj, results, level_out / "shadow_report.md")
        debugger_summary: dict[str, Any] | None = None
        if include_debugger:
            dcases = load_shadow_results(level_out / "shadow_results.jsonl")
            dreport = build_debugger_report(dcases)
            write_debugger_outputs(dreport, level_out)
            debugger_summary = {
                "failed_count": dreport.failed_count,
                "p0_action_count": len(dreport.p0_actions),
                "p1_action_count": len(dreport.p1_actions),
                "p2_action_count": len(dreport.p2_actions),
                "failure_category_counts": dreport.failure_category_counts,
            }
        return HardModeRunResult(
            level=level,
            policy=policy,
            result_count=len(results),
            summary=asdict(summary_obj),
            debugger_summary=debugger_summary,
            output_dir=str(level_out),
        )
    except Exception as exc:  # noqa: BLE001
        return HardModeRunResult(
            level=level,
            policy=policy,
            result_count=0,
            summary={"error": f"{type(exc).__name__}: {str(exc)[:200]}", "total": 0},
            debugger_summary=None,
            output_dir=str(level_out),
        )


def compare_ablation_runs(runs: list[HardModeRunResult]) -> dict[str, Any]:
    rows = []
    for run in runs:
        s = run.summary or {}
        dbg = run.debugger_summary or {}
        rows.append(
            {
                "level": run.level,
                "candidate_budget": run.policy.get("candidate_budget", "unknown"),
                "verifier_level": run.policy.get("verifier_level", "unknown"),
                "require_trace": run.policy.get("require_trace", "unknown"),
                "proof_guardian": run.policy.get("proof_guardian", "unknown"),
                "shadow_eval_required": run.policy.get(
                    "shadow_eval_required", "unknown"
                ),
                "debugger_required": run.policy.get("debugger_required", "unknown"),
                "total": s.get("total", run.result_count),
                "exact_match_count": s.get("exact_match_count", 0),
                "json_valid_rate": s.get("json_valid_rate", 0.0),
                "missing_final_count": s.get("missing_final_count", 0),
                "dirty_boxed_count": s.get("dirty_boxed_count", 0),
                "boxed_42_fallback_count": s.get("boxed_42_fallback_count", 0),
                "failure_category_counts": s.get("failure_category_counts", {}),
                "p0_action_count": dbg.get("p0_action_count", 0),
                "p1_action_count": dbg.get("p1_action_count", 0),
                "p2_action_count": dbg.get("p2_action_count", 0),
            }
        )
    return {"levels": rows}


def _build_recommendation(runs: list[HardModeRunResult]) -> list[str]:
    rec = []
    strict = next((r for r in runs if r.level == "strict"), None)
    off = next((r for r in runs if r.level == "off"), None)
    standard = next((r for r in runs if r.level == "standard"), None)
    if strict and (strict.debugger_summary or {}).get("p0_action_count", 0) > 0:
        rec.append("strict level has P0 actions; do not enable strict by default.")
    if standard and off:
        if standard.policy.get("require_trace") and standard.policy.get(
            "proof_guardian"
        ) != off.policy.get("proof_guardian"):
            if standard.summary.get("exact_match_count", 0) >= off.summary.get(
                "exact_match_count", 0
            ):
                rec.append(
                    "standard adds policy controls without mock metric regression; consider controlled CLI hook in P12."
                )
    if any(
        r.summary.get("missing_final_count", 0) > 0
        or r.summary.get("json_valid_rate", 1) < 1
        for r in runs
    ):
        rec.append("formatter issues detected; prioritize formatter repair.")
    if any(
        (r.summary.get("failure_category_counts", {}) or {}).get("wrong_answer", 0) > 0
        for r in runs
    ):
        rec.append(
            "wrong_answer appears; prioritize verifier/voting/candidate budget experiments."
        )
    if any(
        (r.summary.get("failure_category_counts", {}) or {}).get("proof_partial", 0) > 0
        for r in runs
    ):
        rec.append("proof_partial appears; prioritize proof_guardian rubric iteration.")
    if all((r.debugger_summary or {}).get("failed_count", 0) == 0 for r in runs):
        rec.append("all levels passed on current mock set; add harder shadow cases.")
    return rec or [
        "No strong recommendation from current mock/shadow ablation signals."
    ]


def run_hard_mode_ablation(config: HardModeAblationConfig) -> HardModeAblationReport:
    cases = load_cases(config.input_path)
    if config.limit:
        cases = cases[: config.limit]
    runs = []
    for level in config.levels:
        try:
            runs.append(
                run_single_level_ablation(
                    level=level,
                    cases=cases,
                    out_dir=Path(config.out_dir) / "levels" / level,
                    include_debugger=config.include_debugger,
                )
            )
        except Exception as exc:  # noqa: BLE001
            runs.append(
                HardModeRunResult(
                    level=level,
                    policy=asdict(build_hard_mode_policy(enabled=True, level=level)),
                    result_count=0,
                    summary={
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        "total": 0,
                    },
                    debugger_summary=None,
                    output_dir=str(Path(config.out_dir) / "levels" / level),
                )
            )
    comparison = compare_ablation_runs(runs)
    return HardModeAblationReport(
        levels=config.levels,
        total_cases=len(cases),
        runs=runs,
        comparison=comparison,
        recommendation=_build_recommendation(runs),
        official_warning="This is NOT official evaluation.",
    )


def render_hard_mode_ablation_report(report: HardModeAblationReport) -> str:
    return (
        "\n".join(
            [
                "# Hard Mode Ablation Report",
                "",
                "This is NOT official evaluation.",
                "This report is derived from mock / preofficial / shadow evaluation outputs.",
                "Do not claim official accuracy from this report.",
                "",
                "## 1. Summary",
                f"- Levels: {', '.join(report.levels)}",
                f"- Total Cases: {report.total_cases}",
                "",
                "## 2. Policy Levels",
                *[f"- {r.level}: {r.policy}" for r in report.runs],
                "",
                "## 3. Comparison Table",
                json.dumps(report.comparison, ensure_ascii=False, indent=2),
                "",
                "## 4. Shadow Eval Metrics",
                *[
                    f"- {r.level}: exact_match={r.summary.get('exact_match_count', 0)} json_valid_rate={r.summary.get('json_valid_rate', 0)}"
                    for r in report.runs
                ],
                "",
                "## 5. Debugger Findings",
                *[f"- {r.level}: {r.debugger_summary}" for r in report.runs],
                "",
                "## 6. P0 / P1 / P2 Actions",
                *[
                    f"- {r.level}: P0={((r.debugger_summary or {}).get('p0_action_count',0))}, P1={((r.debugger_summary or {}).get('p1_action_count',0))}, P2={((r.debugger_summary or {}).get('p2_action_count',0))}"
                    for r in report.runs
                ],
                "",
                "## 7. Recommendation",
                *[f"- {x}" for x in report.recommendation],
                "",
                "## 8. Limitations",
                "- Hard-mode is currently policy-layer evidence only.",
                "- Default pipeline behavior is unchanged.",
                "- strict does not guarantee stronger outcomes.",
                "- mock/shadow results are not official.",
                "",
                "## 9. Next Steps",
                "- Use findings to scope controlled follow-ups.",
                "",
                "## 10. Official Submission Warning",
                f"- {report.official_warning}",
            ]
        )
        + "\n"
    )


def write_hard_mode_ablation_outputs(
    report: HardModeAblationReport, out_dir: Path | str
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "hard_mode_ablation_summary.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "comparison.json").write_text(
        json.dumps(report.comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "hard_mode_ablation_report.md").write_text(
        render_hard_mode_ablation_report(report), encoding="utf-8"
    )
