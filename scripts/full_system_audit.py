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
EXCLUDED_PREFIXES = {
    ".git",
    "outputs",
    "trace",
    "traces",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".zip",
    ".pth",
    ".pt",
    ".onnx",
    ".pdf",
    ".docx",
}
CODE_EXTS = {".py", ".sh", ".yml", ".yaml", ".toml", ".json"}


@dataclass
class CheckResult:
    name: str
    command: list[str]
    returncode: int
    status: str
    summary: str


def run_cmd(command: list[str], cwd: Path, timeout: int = 600) -> CheckResult:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        out = (proc.stdout + "\n" + proc.stderr).strip()
        summary = "\n".join(out.splitlines()[:20])
        return CheckResult(
            " ".join(command),
            command,
            proc.returncode,
            "PASS" if proc.returncode == 0 else "FAIL",
            summary,
        )
    except FileNotFoundError as exc:
        return CheckResult(" ".join(command), command, 127, "MISSING", str(exc))


def should_skip(path: Path) -> bool:
    return (
        any(part in EXCLUDED_PREFIXES for part in path.parts)
        or path.suffix.lower() in EXCLUDED_SUFFIXES
    )


def read_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def module_of(path: Path) -> str:
    p = str(path)
    if p in {
        "src/math_agent/pipeline.py",
        "src/math_agent/cli.py",
        "src/math_agent/schemas.py",
    }:
        return "core_pipeline"
    mapping = {
        "src/math_agent/agents/": "agents",
        "src/math_agent/control/": "control_hard_mode",
        "src/math_agent/evaluation/": "evaluation_shadow_ablation",
        "src/math_agent/debugger/": "debugger",
        "src/math_agent/proof/": "proof_guardian",
        "src/math_agent/submission/": "submission_dry_run",
        "src/math_agent/evidence/": "evidence_demo_pack",
        "src/math_agent/verification/": "verification_voting",
        "src/math_agent/harness/": "harness",
        "src/math_agent/tools/": "tools",
        "src/math_agent/clients/": "clients",
        "scripts/": "scripts",
        "tests/": "tests",
        "docs/": "docs",
        "configs/": "configs",
    }
    for k, v in mapping.items():
        if p.startswith(k):
            return v
    if path.name == "README.md":
        return "docs"
    if path.name == "pyproject.toml" or path.suffix.lower() in {
        ".yaml",
        ".yml",
        ".toml",
        ".json",
    }:
        return "configs"
    return "other"


def count_lines(root: Path) -> dict[str, Any]:
    git = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=False
    )
    files = [Path(x) for x in git.stdout.splitlines() if x.strip()]
    by_ext: dict[str, int] = {}
    by_top: dict[str, int] = {}
    by_module: dict[str, int] = {}
    biggest: list[dict[str, Any]] = []
    total = code = tests = docs = 0
    for rel in files:
        if should_skip(rel):
            continue
        full = root / rel
        if not full.is_file():
            continue
        lines = read_lines(full)
        total += lines
        ext = rel.suffix.lower() or "<no_ext>"
        by_ext[ext] = by_ext.get(ext, 0) + lines
        top = rel.parts[0] if rel.parts else "<root>"
        by_top[top] = by_top.get(top, 0) + lines
        mod = module_of(rel)
        by_module[mod] = by_module.get(mod, 0) + lines
        if ext in CODE_EXTS:
            code += lines
        if rel.parts and rel.parts[0] == "tests":
            tests += lines
        if (
            rel.name == "README.md"
            or ext == ".md"
            or (rel.parts and rel.parts[0] == "docs")
        ):
            docs += lines
        biggest.append({"file": str(rel), "lines": lines})
    biggest.sort(key=lambda x: x["lines"], reverse=True)
    return {
        "total_tracked_lines": total,
        "total_code_lines": code,
        "total_test_lines": tests,
        "total_docs_lines": docs,
        "by_extension": dict(sorted(by_ext.items())),
        "by_top_level": dict(sorted(by_top.items())),
        "by_module": dict(sorted(by_module.items())),
        "top_20_files": biggest[:20],
        "method": "git ls-files + Python line reading; no cloc/tokei",
    }


def cleanup_before_safety(root: Path) -> None:
    shutil.rmtree(root / ".pytest_cache", ignore_errors=True)
    for p in root.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    traces = root / "outputs/traces"
    if traces.exists():
        for child in traces.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)


def run_smokes(root: Path, out_dir: Path, include_demo: bool) -> list[CheckResult]:
    cmds = [
        [
            "python",
            "-m",
            "math_agent.cli",
            "solve",
            "--question",
            "计算 2+3",
            "--enable-tools",
            "--mode",
            "fast",
            "--no-trace",
        ],
        [
            "python",
            "-m",
            "math_agent.cli",
            "solve",
            "--question",
            "计算 2+3",
            "--enable-tools",
            "--mode",
            "fast",
            "--no-trace",
            "--hard-mode",
            "--hard-mode-level",
            "light",
        ],
        [
            "python",
            "scripts/shadow_eval.py",
            "--mock",
            "--limit",
            "5",
            "--out",
            str(out_dir / "shadow_eval"),
        ],
        [
            "python",
            "scripts/build_eval_report.py",
            "--results",
            str(out_dir / "shadow_eval/shadow_results.jsonl"),
            "--out-dir",
            str(out_dir / "shadow_eval"),
        ],
        [
            "python",
            "scripts/debug_shadow_failures.py",
            "--results",
            str(out_dir / "shadow_eval/shadow_results.jsonl"),
            "--out-dir",
            str(out_dir / "debugger"),
        ],
    ]
    if include_demo:
        sample = out_dir / "preofficial_sample.jsonl"
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_text(
            '{"question_id":"audit_1","question":"计算 2+3"}\n{"question_id":"audit_2","question":"证明偶数加偶数仍为偶数"}\n',
            encoding="utf-8",
        )
        cmds.extend(
            [
                [
                    "python",
                    "scripts/run_hard_mode_ablation.py",
                    "--limit",
                    "5",
                    "--include-debugger",
                    "--out-dir",
                    str(out_dir / "hard_mode_ablation"),
                ],
                [
                    "python",
                    "scripts/run_proof_guardian_demo.py",
                    "--out-dir",
                    str(out_dir / "proof_guardian_demo"),
                ],
                [
                    "python",
                    "scripts/run_official_dry_run.py",
                    "--input",
                    str(sample),
                    "--out-dir",
                    str(out_dir / "official_dry_run"),
                    "--limit",
                    "2",
                    "--enable-tools",
                    "--mock",
                    "--no-trace",
                ],
                [
                    "python",
                    "scripts/generate_demo_pack.py",
                    "--shadow-dir",
                    str(out_dir / "shadow_eval"),
                    "--debugger-dir",
                    str(out_dir / "debugger"),
                    "--ablation-dir",
                    str(out_dir / "hard_mode_ablation"),
                    "--proof-dir",
                    str(out_dir / "proof_guardian_demo"),
                    "--dry-run-dir",
                    str(out_dir / "official_dry_run"),
                    "--out-dir",
                    str(out_dir / "demo_pack"),
                ],
            ]
        )
    results = []
    for cmd in cmds:
        if not (root / cmd[1]).exists() and cmd[1].startswith("scripts/"):
            results.append(
                CheckResult(" ".join(cmd), cmd, 127, "MISSING", "script not found")
            )
        else:
            results.append(run_cmd(cmd, root, timeout=900))
    return results


def write_reports(
    out_dir: Path,
    lines: dict[str, Any],
    quality: list[CheckResult],
    smoke: list[CheckResult],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "line_count_report.json").write_text(
        json.dumps(lines, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "quality_gate_results.json").write_text(
        json.dumps([asdict(x) for x in quality], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "functional_smoke_results.json").write_text(
        json.dumps([asdict(x) for x in smoke], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary = {
        "line_counts": lines,
        "quality_pass": all(x.status == "PASS" for x in quality),
        "smoke_pass": all(x.status in {"PASS", "MISSING"} for x in smoke),
        "disclaimer": DISCLAIMER,
    }
    (out_dir / "full_system_audit_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "line_count_report.md").write_text(
        f"# Line Count Report\n\n{DISCLAIMER}\n\n- total_code_lines: {lines['total_code_lines']}\n- method: {lines['method']}\n",
        encoding="utf-8",
    )
    inventory = (
        "# Function Inventory / 功能清单\n\n"
        + DISCLAIMER
        + "\n\n| 功能 | 文件入口 | 命令入口 | 默认启用 | mock-safe | 外部API | 输出 | 用途 | 阶段 | 风险边界 |\n"
        + "|---|---|---|---|---|---|---|---|---|---|\n"
        + "| CLI solve | src/math_agent/cli.py | python -m math_agent.cli solve | 是 | 是 | 否(默认) | JSON | 基础求解入口 | P18.5 | real 需显式开关 |\n"
        + "| Shadow Eval | scripts/shadow_eval.py | python scripts/shadow_eval.py --mock | 否 | 是 | 否 | shadow_results.jsonl | mock评测 | P18.5 | 非官方成绩 |\n"
        + "| Official-like Dry Run | scripts/run_official_dry_run.py | python scripts/run_official_dry_run.py --mock | 否 | 是 | 否 | dry_run_report | 官方格式模拟 | P18.5 | 禁止 official_results.jsonl |\n"
    )
    (out_dir / "function_inventory.md").write_text(inventory, encoding="utf-8")
    arch = (
        "# Architecture Overview\n\n"
        + DISCLAIMER
        + "\n\n```mermaid\nflowchart TD\n  CLI[CLI solve] --> PIPE[Pipeline]\n  PIPE --> HM[HardModePolicy / Runtime Hook]\n  HM --> CB[Candidate Budget Preview]\n  HM --> VR[Verifier Routing Preview]\n  HM --> WV[Weighted Voting Preview]\n  HM --> PG[Proof Guardian Preview]\n  PIPE --> SE[Shadow Eval]\n  SE --> DBG[Agent Debugger]\n  SE --> ABL[Hard-mode Ablation]\n  PIPE --> DRY[Official-like Dry Run]\n  DBG --> DEMO[Demo Evidence Pack]\n  ABL --> DEMO\n  PG --> DEMO\n  DRY --> DEMO\n  DEMO --> DEFENSE[Defense / README / Reports]\n  SAFETY[Safety Gate] --> DEMO\n```\n"
    )
    (out_dir / "architecture_overview.md").write_text(arch, encoding="utf-8")
    (out_dir / "readme_update_notes.md").write_text(
        "# README Update Notes\n\n" + DISCLAIMER + "\n", encoding="utf-8"
    )
    (out_dir / "full_system_audit_report.md").write_text(
        "# Full System Audit Report\n\n" + DISCLAIMER + "\n", encoding="utf-8"
    )


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
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (root / out_dir).resolve()
    lines = count_lines(root)
    quality_cmds = [
        ["ruff", "check", "."],
        ["black", "--check", "src", "scripts", "demo", "tests"],
        ["isort", "--check-only", "--diff", "src", "scripts", "demo", "tests"],
        ["mypy", "src", "--show-error-codes"],
        ["pyright"],
        ["python", "-m", "compileall", "src", "scripts", "demo", "tests"],
    ]
    if not args.skip_slow:
        quality_cmds.append(["python", "-m", "pytest", "-q"])
    cleanup_before_safety(root)
    quality_cmds.append(["python", "scripts/check_project_safety.py"])
    quality = [run_cmd(c, root, timeout=1200) for c in quality_cmds]
    smoke = run_smokes(root, out_dir, args.include_demo_smoke)
    write_reports(out_dir, lines, quality, smoke)
    critical_fail = any(x.status == "FAIL" for x in quality)
    if args.fail_on_risk and critical_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
