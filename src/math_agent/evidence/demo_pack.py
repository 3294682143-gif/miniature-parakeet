from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OFFICIAL_WARNING = (
    "This is NOT official evaluation. "
    "This pack is for demo / defense / engineering evidence only. "
    "Do not claim official accuracy from this pack. "
    "Do not rename any dry-run output to official_results.jsonl."
)


@dataclass
class EvidenceSource:
    name: str
    path: str
    exists: bool
    kind: str
    summary: dict[str, Any]
    warnings: list[str]


@dataclass
class DemoCase:
    case_id: str
    title: str
    category: str
    source: str
    domain: str
    difficulty: str
    failure_category: str | None
    demo_angle: str
    evidence_path: str | None
    notes: list[str]


@dataclass
class DemoEvidencePack:
    run_id: str
    created_at: str
    sources: list[EvidenceSource]
    demo_cases: list[DemoCase]
    summary: dict[str, Any]
    warnings: list[str]
    official_warning: str


def _parse_json(path: Path, warnings: list[str]) -> Any:
    if not path.is_file():
        warnings.append(f"missing:{path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        warnings.append(f"parse_error:{path.name}")
        return {"parse_error": str(exc)}


def _pick_path(explicit: str | None, defaults: list[str]) -> Path:
    if explicit:
        return Path(explicit)
    for d in defaults:
        p = Path(d)
        if p.exists():
            return p
    return Path(defaults[0])


def _source(
    name: str, path: Path, summary: dict[str, Any], warnings: list[str]
) -> EvidenceSource:
    if not path.exists():
        warnings.append(f"source_missing:{path}")
    return EvidenceSource(
        name=name,
        path=str(path),
        exists=path.exists(),
        kind="dir",
        summary=summary,
        warnings=warnings,
    )


def collect_evidence_sources(
    shadow_dir: str | None = None,
    debugger_dir: str | None = None,
    ablation_dir: str | None = None,
    proof_dir: str | None = None,
    dry_run_dir: str | None = None,
    project_health_json: str | None = None,
) -> list[EvidenceSource]:
    sources: list[EvidenceSource] = []

    shadow = _pick_path(
        shadow_dir, ["outputs/shadow_eval_test", "outputs/shadow_eval_gate"]
    )
    sw: list[str] = []
    s = _parse_json(shadow / "shadow_summary.json", sw) if shadow.exists() else None
    ss = s if isinstance(s, dict) else {}
    sources.append(
        _source(
            "shadow_eval",
            shadow,
            {
                "total": ss.get("total"),
                "exact_match_count": ss.get("exact_match_count"),
                "json_valid_rate": ss.get("json_valid_rate"),
                "missing_final_count": ss.get("missing_final_count"),
                "dirty_boxed_count": ss.get("dirty_boxed_count"),
                "boxed_42_fallback_count": ss.get("boxed_42_fallback_count"),
                "failure_category_counts": ss.get("failure_category_counts"),
                "domain_breakdown": ss.get("domain_breakdown"),
                "difficulty_breakdown": ss.get("difficulty_breakdown"),
            },
            sw,
        )
    )

    dbg = _pick_path(debugger_dir, ["outputs/debug_shadow"])
    dw: list[str] = []
    clusters = _parse_json(dbg / "failure_clusters.json", dw) if dbg.exists() else None
    root_causes = _parse_json(dbg / "root_causes.json", dw) if dbg.exists() else None
    sources.append(
        _source(
            "agent_debugger",
            dbg,
            {
                "failure_clusters_count": (
                    len(clusters) if isinstance(clusters, list) else None
                ),
                "top_failure_categories": (
                    [c.get("key") for c in clusters[:5]]
                    if isinstance(clusters, list)
                    else None
                ),
                "p0_actions": (
                    root_causes.get("p0_actions")
                    if isinstance(root_causes, dict)
                    else None
                ),
                "p1_actions": (
                    root_causes.get("p1_actions")
                    if isinstance(root_causes, dict)
                    else None
                ),
                "p2_actions": (
                    root_causes.get("p2_actions")
                    if isinstance(root_causes, dict)
                    else None
                ),
                "representative_failures": (
                    root_causes.get("representative_failures")
                    if isinstance(root_causes, dict)
                    else None
                ),
            },
            dw,
        )
    )

    abl = _pick_path(ablation_dir, ["outputs/hard_mode_ablation"])
    aw: list[str] = []
    ab_summary = (
        _parse_json(abl / "hard_mode_ablation_summary.json", aw)
        if abl.exists()
        else None
    )
    comp = _parse_json(abl / "comparison.json", aw) if abl.exists() else None
    s1 = ab_summary if isinstance(ab_summary, dict) else {}
    c1 = comp if isinstance(comp, dict) else {}
    sources.append(
        _source(
            "hard_mode_ablation",
            abl,
            {
                "levels": s1.get("levels") or c1.get("levels"),
                "comparison_rows": s1.get("comparison_rows") or c1.get("rows"),
                "recommendations": s1.get("recommendations"),
                "strict_p0_count": s1.get("strict_p0_count"),
                "strict_p1_count": s1.get("strict_p1_count"),
                "strict_p2_count": s1.get("strict_p2_count"),
                "standard_vs_off_notes": s1.get("standard_vs_off_notes"),
            },
            aw,
        )
    )

    proof = _pick_path(proof_dir, ["outputs/proof_guardian_demo"])
    pw: list[str] = []
    p = _parse_json(proof / "proof_guardian_demo.json", pw) if proof.exists() else None
    pd = p if isinstance(p, dict) else {}
    sources.append(
        _source(
            "proof_guardian",
            proof,
            {
                "complete_examples": pd.get("complete") or pd.get("complete_examples"),
                "partial_examples": pd.get("partial") or pd.get("partial_examples"),
                "invalid_examples": pd.get("invalid") or pd.get("invalid_examples"),
                "proof_guardian_decision": pd.get("decision"),
                "proof_risk_flags": pd.get("risk_flags"),
            },
            pw,
        )
    )

    dry = _pick_path(dry_run_dir, ["outputs/official_dry_run"])
    rw: list[str] = []
    d = _parse_json(dry / "dry_run_summary.json", rw) if dry.exists() else None
    dd = d if isinstance(d, dict) else {}
    sources.append(
        _source(
            "official_dry_run",
            dry,
            {
                "run_id": dd.get("run_id"),
                "total": dd.get("total"),
                "success_count": dd.get("success_count"),
                "fail_count": dd.get("fail_count"),
                "invalid_count": dd.get("invalid_count"),
                "missing_final_count": dd.get("missing_final_count"),
                "average_latency_ms": dd.get("average_latency_ms"),
                "trace_dir": dd.get("trace_dir"),
                "results_path": dd.get("results_path"),
            },
            rw,
        )
    )

    hp = _pick_path(
        project_health_json,
        ["outputs/project_health_report.json", "project_health_report.json"],
    )
    hw: list[str] = []
    h = _parse_json(hp, hw)
    hd = h if isinstance(h, dict) else {}
    sources.append(
        EvidenceSource(
            name="project_health",
            path=str(hp),
            exists=hp.exists(),
            kind="json",
            warnings=hw,
            summary={
                "commit": (
                    hd.get("git", {}).get("commit_short")
                    if isinstance(hd.get("git"), dict)
                    else hd.get("commit")
                ),
                "branch": (
                    hd.get("git", {}).get("branch")
                    if isinstance(hd.get("git"), dict)
                    else hd.get("branch")
                ),
                "code_lines": (
                    hd.get("lines", {}).get("total_lines")
                    if isinstance(hd.get("lines"), dict)
                    else hd.get("code_lines")
                ),
                "pytest_count": (
                    hd.get("assets", {}).get("test_file_count")
                    if isinstance(hd.get("assets"), dict)
                    else hd.get("pytest_count")
                ),
                "ci_status": (
                    hd.get("ci", {}).get("ci_status")
                    if isinstance(hd.get("ci"), dict)
                    else hd.get("ci_status")
                ),
                "safety_status": (
                    hd.get("quality_gates", {}).get("safety_scan")
                    if isinstance(hd.get("quality_gates"), dict)
                    else hd.get("safety_status")
                ),
                "gate_coverage": hd.get("quality_gates"),
            },
        )
    )
    return sources


def build_demo_cases(sources: list[EvidenceSource], limit: int = 12) -> list[DemoCase]:
    cases: list[DemoCase] = []
    for src in sources:
        angle = (
            "show graceful degradation"
            if not src.exists
            else "show key summary metrics"
        )
        cat = "missing_source" if not src.exists else "overview"
        notes = (
            ["source missing"] if not src.exists else [f"warnings={len(src.warnings)}"]
        )
        failure_category = None
        if src.name == "agent_debugger" and isinstance(
            src.summary.get("top_failure_categories"), list
        ):
            top = src.summary["top_failure_categories"]
            failure_category = top[0] if top else None
        cases.append(
            DemoCase(
                case_id=f"{src.name}-demo",
                title=f"{src.name} demo case",
                category=cat,
                source=src.name,
                domain="general",
                difficulty="mixed",
                failure_category=failure_category,
                demo_angle=angle,
                evidence_path=src.path,
                notes=notes,
            )
        )
    return cases[:limit]


def build_demo_evidence_pack(limit_cases: int = 12, **kwargs: Any) -> DemoEvidencePack:
    sources = collect_evidence_sources(**kwargs)
    warnings = [w for s in sources for w in s.warnings]
    return DemoEvidencePack(
        run_id=datetime.now(UTC).strftime("demo-pack-%Y%m%d-%H%M%S"),
        created_at=datetime.now(UTC).isoformat(),
        sources=sources,
        demo_cases=build_demo_cases(sources, limit=limit_cases),
        summary={
            "total_sources": len(sources),
            "available_sources": sum(1 for s in sources if s.exists),
            "missing_sources": [s.name for s in sources if not s.exists],
        },
        warnings=warnings,
        official_warning=OFFICIAL_WARNING,
    )


def write_demo_evidence_pack(
    pack: DemoEvidencePack, out_dir: str | Path, output_format: str = "markdown"
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidence_summary.json").write_text(
        json.dumps(asdict(pack), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "evidence_sources.json").write_text(
        json.dumps([asdict(x) for x in pack.sources], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "demo_cases.json").write_text(
        json.dumps([asdict(x) for x in pack.demo_cases], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if output_format == "json":
        return

    from .report import (
        render_architecture_summary,
        render_demo_index,
        render_demo_script,
        render_dry_run_summary,
        render_hard_mode_summary,
        render_proof_guardian_summary,
        render_readme,
        render_risk_control_summary,
    )

    (out / "demo_index.md").write_text(render_demo_index(pack), encoding="utf-8")
    (out / "demo_script.md").write_text(render_demo_script(pack), encoding="utf-8")
    (out / "architecture_summary.md").write_text(
        render_architecture_summary(pack), encoding="utf-8"
    )
    (out / "risk_control_summary.md").write_text(
        render_risk_control_summary(pack), encoding="utf-8"
    )
    (out / "hard_mode_summary.md").write_text(
        render_hard_mode_summary(pack), encoding="utf-8"
    )
    (out / "proof_guardian_summary.md").write_text(
        render_proof_guardian_summary(pack), encoding="utf-8"
    )
    (out / "dry_run_summary.md").write_text(
        render_dry_run_summary(pack), encoding="utf-8"
    )
    (out / "README_DEMO_PACK.md").write_text(render_readme(pack), encoding="utf-8")
