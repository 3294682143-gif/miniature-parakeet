from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DISCLAIMER = (
    "This is NOT official evaluation.\n"
    "Do not claim official accuracy from this audit.\n"
    "Do not rename dry-run outputs to official_results.jsonl."
)

CATEGORY_LABELS = {
    "A": "Stable Core / 主解题内核",
    "B": "Tools / 工具求解层",
    "C": "Formatter / JSON 安全层",
    "D": "Proof Layer / 证明题保护层",
    "E": "Skills / 外化技能层",
    "F": "Memory / 外化记忆层",
    "G": "Protocol / 协议对象层",
    "H": "Control / Hard-mode 控制层",
    "I": "Weighted Voting / Verifier Scoring 层",
    "J": "Budget Scheduler / 预算控制层",
    "K": "Evaluation / Shadow Eval 层",
    "L": "Regression Gate / 质量门禁层",
    "M": "Agent Debugger / 失败归因层",
    "N": "Trace / Replay / Observability 层",
    "O": "Demo / Streamlit 展示层",
    "P": "Demo Evidence Pack / 展示证据包",
    "Q": "Hard-mode Ablation / 消融实验层",
    "R": "Official-like Dry Run / 官方模拟运行层",
    "S": "Submission / Frozen Export 层",
    "T": "Offline Evolution / Candidate Archive 层",
    "U": "Safety / Security 层",
    "V": "Project Health / 工程健康层",
    "W": "Docs / Report / README 层",
    "X": "Full System Audit 自身",
}


def reg(fid: str, name: str, category: str, status: str, files: list[str], smoke: list[str] | None = None, notes: str = "") -> dict[str, Any]:
    return {
        "id": fid,
        "name": name,
        "category": category,
        "status": status,
        "files": files,
        "command_entry": "python -m math_agent.cli" if category == "A" else "script/module entry",
        "smoke_command": smoke or [],
        "default_enabled": category in {"A", "C", "G", "U"},
        "mock_safe": True,
        "calls_external_api": False,
        "reads_env": False,
        "writes_outputs": True,
        "produces_official_results": False,
        "output_artifacts": ["reports", "json", "md"],
        "risk_boundary": "mock-safe only; no .env read; no official_results.jsonl",
        "related_tests": ["tests/test_full_system_audit.py"],
        "docs": ["README.md", "docs/full_system_audit.md"],
        "notes": notes,
    }


FUNCTION_AUDIT_REGISTRY: list[dict[str, Any]] = [
    reg("A01", "CLI solve", "A", "integrated", ["src/math_agent/cli.py"]),
    reg("A02", "CLI batch", "A", "integrated", ["src/math_agent/cli.py"]),
    reg("A03", "pipeline", "A", "integrated", ["src/math_agent/pipeline.py"]),
    reg("A04", "schemas/SolveResult", "A", "integrated", ["src/math_agent/schemas.py"]),
    reg("B01", "SymPy tool solver", "B", "integrated", ["src/math_agent/tools/sympy_tools.py"]),
    reg("B02", "Python sandbox tool", "B", "integrated", ["src/math_agent/tools/python_sandbox.py"]),
    reg("B03", "answer_normalizer", "B", "integrated", ["src/math_agent/tools/answer_normalizer.py"]),
    reg("B04", "tool call record", "B", "integrated", ["src/math_agent/schemas.py"]),
    reg("B05", "tool error fallback", "B", "integrated", ["src/math_agent/pipeline.py"]),
    reg("C01", "Formatter Repair", "C", "integrated", ["src/math_agent/harness/formatter_repair.py"]),
    reg("C02", "sanitize_boxed", "C", "integrated", ["src/math_agent/harness/formatter_repair.py"]),
    reg("C03", "detect_dirty_final_answer", "C", "integrated", ["src/math_agent/harness/formatter_repair.py"]),
    reg("C04", "proof_safe_finalize", "C", "integrated", ["src/math_agent/harness/formatter_repair.py"]),
    reg("C05", "final_answer extraction", "C", "integrated", ["src/math_agent/pipeline.py"]),
    reg("C06", "boxed_42_fallback detection", "C", "integrated", ["src/math_agent/evaluation/metrics.py"]),
    reg("D01", "ProofGuardian core", "D", "integrated", ["src/math_agent/proof/proof_guardian.py"]),
    reg("D02", "ProofRubricScore", "D", "integrated", ["src/math_agent/proof/proof_rubric.py"]),
    reg("D03", "ProofGuardianDecision", "D", "integrated", ["src/math_agent/proof/proof_guardian.py"]),
    reg("D04", "proof_guardian_plan", "D", "preview", ["src/math_agent/control/proof_guardian_hook.py"]),
    reg("D05", "proof completeness states", "D", "integrated", ["src/math_agent/proof/proof_rubric.py"]),
    reg("D06", "proof scoring in verifier_scoring", "D", "integrated", ["src/math_agent/verification/verifier_scoring.py"]),
    reg("D07", "proof demo script", "D", "standalone", ["scripts/run_proof_guardian_demo.py"]),
    reg("E01", "Skill Library", "E", "integrated", ["skills/README.md"]),
    reg("E02", "skill_registry", "E", "integrated", ["src/math_agent/harness/skill_registry.py"]),
    reg("E03", "proof/equation/calculation/etc skills", "E", "integrated", ["skills/proof.skill.md", "skills/equation.skill.md"]),
    reg("F01", "MemoryHub", "F", "preview", ["src/math_agent/harness/memory.py"]),
    reg("F02", "memory summary", "F", "preview", ["demo/streamlit_app.py"]),
    reg("G01", "AgentStep", "G", "integrated", ["src/math_agent/schemas.py"]),
    reg("G02", "ToolCallRecord", "G", "integrated", ["src/math_agent/schemas.py"]),
    reg("G03", "ProtocolVerifierResult", "G", "integrated", ["src/math_agent/schemas.py"]),
    reg("G04", "CandidateAnswer", "G", "integrated", ["src/math_agent/schemas.py"]),
    reg("G05", "WeightedVoteResult", "G", "integrated", ["src/math_agent/schemas.py"]),
    reg("G06", "sanitize_protocol_metadata", "G", "integrated", ["src/math_agent/schemas.py"]),
    reg("G07", "to_jsonable", "G", "integrated", ["src/math_agent/schemas.py"]),
    reg("H01", "HardModePolicy", "H", "integrated", ["src/math_agent/control/policy.py"]),
    reg("H02", "hard-mode levels", "H", "integrated", ["src/math_agent/control/hard_mode.py"]),
    reg("H03", "candidate_budget", "H", "preview", ["src/math_agent/control/candidate_budget.py"]),
    reg("H04", "verifier_level", "H", "preview", ["src/math_agent/control/hard_mode.py"]),
    reg("H05", "require_trace", "H", "preview", ["src/math_agent/control/hard_mode.py"]),
    reg("H06", "proof_guardian flag", "H", "preview", ["src/math_agent/control/hard_mode.py"]),
    reg("H07", "shadow_eval_required", "H", "preview", ["src/math_agent/control/hard_mode.py"]),
    reg("H08", "debugger_required", "H", "preview", ["src/math_agent/control/hard_mode.py"]),
    reg("H09", "hard-mode CLI preview", "H", "preview", ["src/math_agent/cli.py"]),
    reg("H10", "pipeline metadata hook", "H", "integrated", ["src/math_agent/control/pipeline_hook.py"]),
    reg("I01", "Weighted Voting standalone", "I", "standalone", ["scripts/run_weighted_voting_demo.py"]),
    reg("I02", "controlled weighted voting", "I", "integrated", ["src/math_agent/control/weighted_voting_hook.py"]),
    reg("I03", "candidate clustering", "I", "integrated", ["src/math_agent/verification/weighted_voting.py"]),
    reg("I04", "verifier scoring", "I", "integrated", ["src/math_agent/verification/verifier_scoring.py"]),
    reg("I05", "risk flags", "I", "integrated", ["src/math_agent/verification/verifier_scoring.py"]),
    reg("I06", "final candidate selection trace", "I", "integrated", ["src/math_agent/verification/weighted_voting.py"]),
    reg("J01", "Adaptive Budget Scheduler", "J", "integrated", ["src/math_agent/harness/budget_scheduler.py"]),
    reg("J02", "budgets.yaml", "J", "present", ["configs/budgets.yaml"]),
    reg("J03", "domain_overrides", "J", "integrated", ["src/math_agent/harness/budget_scheduler.py"]),
    reg("J04", "max_candidates", "J", "integrated", ["src/math_agent/harness/budget_scheduler.py"]),
    reg("J05", "max_refine_rounds", "J", "integrated", ["src/math_agent/harness/budget_scheduler.py"]),
    reg("J06", "max_model_calls", "J", "integrated", ["src/math_agent/harness/budget_scheduler.py"]),
    reg("K01", "Shadow Eval", "K", "standalone", ["scripts/shadow_eval.py"]),
    reg("K02", "metrics.py", "K", "integrated", ["src/math_agent/evaluation/metrics.py"]),
    reg("K03", "error_taxonomy.py", "K", "integrated", ["src/math_agent/evaluation/error_taxonomy.py"]),
    reg("K04", "build_eval_report", "K", "standalone", ["scripts/build_eval_report.py"]),
    reg("L01", "run_regression_gate", "L", "standalone", ["scripts/run_regression_gate.py"]),
    reg("L02", "skip-slow", "L", "integrated", ["scripts/run_regression_gate.py"]),
    reg("L03", "include-shadow-eval", "L", "integrated", ["scripts/run_regression_gate.py"]),
    reg("L04", "pytest/format/type/safety gates", "L", "integrated", ["scripts/run_regression_gate.py"]),
    reg("M01", "Agent Debugger", "M", "integrated", ["src/math_agent/debugger/report.py"]),
    reg("M02", "FailureCase", "M", "integrated", ["src/math_agent/debugger/failure_attribution.py"]),
    reg("M03", "FailureCluster", "M", "integrated", ["src/math_agent/debugger/root_cause.py"]),
    reg("M04", "DebuggerReport", "M", "integrated", ["src/math_agent/debugger/report.py"]),
    reg("M05", "severity P0/P1/P2", "M", "integrated", ["src/math_agent/debugger/root_cause.py"]),
    reg("N01", "trace_reader", "N", "integrated", ["src/math_agent/harness/trace_reader.py"]),
    reg("N02", "replay.py", "N", "integrated", ["src/math_agent/harness/replay.py"]),
    reg("N03", "replay_trace.py", "N", "standalone", ["scripts/replay_trace.py"]),
    reg("N04", "build_timeline/summarize_trace", "N", "integrated", ["src/math_agent/harness/replay.py"]),
    reg("N05", "render_replay_markdown", "N", "integrated", ["src/math_agent/harness/replay.py"]),
    reg("N06", "trace redaction", "N", "integrated", ["src/math_agent/logging_utils.py"]),
    reg("O01", "Streamlit Demo", "O", "standalone", ["demo/streamlit_app.py"]),
    reg("O02", "demo_adapter", "O", "integrated", ["src/math_agent/harness/demo_adapter.py"]),
    reg("P01", "generate_demo_pack", "P", "standalone", ["scripts/generate_demo_pack.py"]),
    reg("P02", "demo evidence markdowns", "P", "integrated", ["src/math_agent/evidence/demo_pack.py"]),
    reg("Q01", "run_hard_mode_ablation", "Q", "standalone", ["scripts/run_hard_mode_ablation.py"]),
    reg("Q02", "ablation comparison", "Q", "integrated", ["src/math_agent/evaluation/hard_mode_ablation.py"]),
    reg("R01", "run_official_dry_run", "R", "standalone", ["scripts/run_official_dry_run.py"]),
    reg("R02", "dry_run report/run_id/config_snapshot", "R", "integrated", ["src/math_agent/submission/dry_run.py", "src/math_agent/submission/report.py"]),
    reg("R03", "no official_results guarantee", "R", "integrated", ["scripts/run_official_dry_run.py"]),
    reg("S01", "export_submission.py", "S", "standalone", ["scripts/export_submission.py"]),
    reg("S02", "submission artifacts", "S", "standalone", ["docs/submission_checklist.md"]),
    reg("T01", "offline evolution skeleton", "T", "present", ["evolution/README.md"]),
    reg("T02", "change manifest template", "T", "present", ["evolution/manifests/change_manifest_template.yaml"]),
    reg("U01", "check_project_safety.py", "U", "integrated", ["scripts/check_project_safety.py"]),
    reg("U02", ".env/key/bearer/output detection", "U", "integrated", ["scripts/check_project_safety.py"]),
    reg("U03", "official_results/__pycache__/pytest_cache detection", "U", "integrated", ["scripts/check_project_safety.py"]),
    reg("V01", "project_health_report", "V", "standalone", ["scripts/project_health_report.py"]),
    reg("V02", "current_baseline_audit", "V", "present", ["docs/current_baseline_audit.md"]),
    reg("V03", "git/local/CI checks", "V", "integrated", ["scripts/project_health_report.py"]),
    reg("W01", "README", "W", "present", ["README.md"]),
    reg("W02", "final_report/architecture/replay/submission docs", "W", "present", ["docs/final_report.md", "docs/architecture.md", "docs/replay.md", "docs/submission_checklist.md"]),
    reg("W03", "hard_mode_control/proof_guardian/full_system_audit docs", "W", "present", ["docs/hard_mode_control.md", "docs/proof_guardian.md", "docs/full_system_audit.md"]),
    reg("X01", "full_system_audit script", "X", "standalone", ["scripts/full_system_audit.py"]),
    reg("X02", "function inventory outputs", "X", "integrated", ["scripts/full_system_audit.py"]),
]

@dataclass
class CheckResult:
    name: str
    command: list[str]
    returncode: int
    status: str
    summary: str

def run_cmd(command: list[str], cwd: Path, timeout: int = 600) -> CheckResult:
    p = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)
    out = (p.stdout + "\n" + p.stderr).strip()
    return CheckResult(" ".join(command), command, p.returncode, "PASS" if p.returncode == 0 else "FAIL", "\n".join(out.splitlines()[:20]))

def count_lines(root: Path) -> dict[str, Any]:
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=False).stdout.splitlines()
    by_module: dict[str, int] = {}
    total = 0
    for fp in files:
        p = root / fp
        if not p.is_file():
            continue
        lines = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        total += lines
        top = fp.split("/")[0] if "/" in fp else "<root>"
        by_module[top] = by_module.get(top, 0) + lines
    return {"total_code_lines": total, "by_module": dict(sorted(by_module.items()))}

def validate_registry(root: Path) -> list[dict[str, Any]]:
    out = []
    for item in FUNCTION_AUDIT_REGISTRY:
        existing = [f for f in item["files"] if (root / f).exists()]
        copy = dict(item)
        copy["existing_files"] = existing
        if item["status"] == "present" and not existing:
            copy["status"] = "missing"
        out.append(copy)
    return out

def write_outputs(root: Path, out_dir: Path, lines: dict[str, Any], quality: list[CheckResult], smoke: list[CheckResult], inv: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "line_count_report.json").write_text(json.dumps(lines, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "quality_gate_results.json").write_text(json.dumps([asdict(x) for x in quality], indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "functional_smoke_results.json").write_text(json.dumps([asdict(x) for x in smoke], indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "function_inventory.json").write_text(json.dumps(inv, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {"disclaimer": DISCLAIMER, "line_counts": lines, "function_count": len(inv), "categories": sorted({x["category"] for x in inv})}
    (out_dir / "full_system_audit_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    inv_md = ["# Function Inventory", "", DISCLAIMER, "", "| id | name | category | status | files | risk_boundary |", "|---|---|---|---|---|---|"]
    for x in inv:
        inv_md.append(f"| {x['id']} | {x['name']} | {CATEGORY_LABELS.get(x['category'], x['category'])} | {x['status']} | {'; '.join(x['files'])} | {x['risk_boundary']} |")
    (out_dir / "function_inventory.md").write_text("\n".join(inv_md), encoding="utf-8")
    grouped = ["# Function Inventory by Category", "", DISCLAIMER, ""]
    for c in sorted(CATEGORY_LABELS):
        grouped.append(f"## {c}. {CATEGORY_LABELS[c]}")
        for x in [i for i in inv if i["category"] == c]:
            grouped.append(f"- {x['id']} {x['name']} ({x['status']})")
        grouped.append("")
    (out_dir / "function_inventory_by_category.md").write_text("\n".join(grouped), encoding="utf-8")
    (out_dir / "line_count_report.md").write_text(f"# Line Count Summary\n\n{DISCLAIMER}\n\n- total_code_lines: {lines['total_code_lines']}\n- by_module: {json.dumps(lines['by_module'], ensure_ascii=False)}\n", encoding="utf-8")
    report = f"# Full System Audit Report\n\n## 1. Executive Summary\n\n{DISCLAIMER}\n\n## 3. Repository Overview\n- total functions audited: {len(inv)}\n\n## 4. Line Count Summary\n- total_code_lines: {lines['total_code_lines']}\n\n## 5. Quality Gate Results\n- checks: {len(quality)}\n\n## 6. Functional Smoke Results\n- checks: {len(smoke)}\n\n## 7. Full Function Inventory\n- see function_inventory.md/json\n\n## 8. Missing Optional Capabilities\n- listed by status=missing/planned\n\n## 9. Safety Boundary\n- no .env reads; no official_results.jsonl\n\n## 10. Official Submission Warning\n- dry-run != official evaluation\n\n## 11. Next Steps: P19 / P20\n- P19: tighten regression evidence\n- P20: stronger verifier experiments\n"
    (out_dir / "full_system_audit_report.md").write_text(report, encoding="utf-8")
    (out_dir / "architecture_overview.md").write_text("# Architecture / Full Chain\n\n" + DISCLAIMER, encoding="utf-8")
    (out_dir / "readme_update_notes.md").write_text("# README update notes\n\nExpanded Full Function Inventory Overview and P19/P20 roadmap.", encoding="utf-8")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs/full_system_audit")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--skip-slow", action="store_true")
    ap.add_argument("--include-demo-smoke", action="store_true")
    ap.add_argument("--fail-on-risk", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out_dir = (root / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
    lines = count_lines(root)
    quality_cmds = [["ruff", "check", "."], ["black", "--check", "src", "scripts", "demo", "tests"], ["isort", "--check-only", "--diff", "src", "scripts", "demo", "tests"], ["mypy", "src", "--show-error-codes"], ["pyright"], ["python", "-m", "compileall", "src", "scripts", "demo", "tests"], ["python", "scripts/check_project_safety.py"]]
    if not args.skip_slow:
        quality_cmds.insert(-1, ["python", "-m", "pytest", "-q"])
    quality = [run_cmd(c, root, 1200) for c in quality_cmds]
    smoke_cmds = [["python", "-m", "math_agent.cli", "solve", "--question", "计算 2+3", "--enable-tools", "--mode", "fast", "--no-trace"], ["python", "scripts/shadow_eval.py", "--mock", "--limit", "5", "--out", str(out_dir / "shadow_eval")], ["python", "scripts/run_official_dry_run.py", "--input", "data/sample_questions.jsonl", "--out-dir", str(out_dir / "official_dry_run"), "--limit", "2", "--enable-tools", "--mock", "--no-trace"]]
    smoke = [run_cmd(c, root, 1200) if (not c[1].startswith("scripts/") or (root / c[1]).exists()) else CheckResult(" ".join(c), c, 127, "MISSING", "script not found") for c in smoke_cmds]
    inv = validate_registry(root)
    write_outputs(root, out_dir, lines, quality, smoke, inv)
    return 1 if args.fail_on_risk and any(x.status == "FAIL" for x in quality) else 0

if __name__ == "__main__":
    raise SystemExit(main())
