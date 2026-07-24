from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.logging_utils import safe_text_write
from math_agent.security import safe_exception_text

EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pyright",
    "outputs",
    "trace",
    "traces",
    "run_records",
    "submission",
    "dist",
    "build",
    ".venv",
    "venv",
    "node_modules",
}

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
}


def run_cmd(
    cmd: list[str], timeout: int = 15, cwd: Path | None = None
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (subprocess.SubprocessError, OSError) as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": safe_exception_text(exc),
        }


def get_git_info(root: Path) -> dict[str, Any]:
    branch = run_cmd(["git", "branch", "--show-current"], cwd=root)
    commit = run_cmd(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    recent = run_cmd(["git", "log", "--oneline", "-5"], cwd=root)
    status = run_cmd(["git", "status", "--porcelain"], cwd=root)
    remotes = run_cmd(["git", "remote", "-v"], cwd=root)
    remote_state = "unknown"
    if remotes["ok"]:
        remote_state = "present" if remotes["stdout"] else "none"
    return {
        "branch": branch["stdout"] if branch["ok"] and branch["stdout"] else "unknown",
        "commit_short": (
            commit["stdout"] if commit["ok"] and commit["stdout"] else "unknown"
        ),
        "recent_commits": recent["stdout"].splitlines() if recent["ok"] else [],
        "git_status_clean": bool(status["ok"] and not status["stdout"]),
        "has_uncommitted_changes": bool(status["ok"] and status["stdout"]),
        "remote": remote_state,
    }


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def iter_tracked_files(root: Path) -> list[Path]:
    files = run_cmd(["git", "ls-files"], cwd=root)
    if not files["ok"]:
        return [
            p
            for p in root.rglob("*")
            if p.is_file() and not _is_excluded(p.relative_to(root))
        ]
    tracked = []
    for rel in files["stdout"].splitlines():
        rel_path = Path(rel)
        if _is_excluded(rel_path):
            continue
        full = root / rel_path
        if full.is_file():
            tracked.append(full)
    return tracked


def _count_file_lines(path: Path) -> int:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return 0
    try:
        sample = path.read_bytes()[:2048]
        if b"\0" in sample:
            return 0
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def count_lines(root: Path) -> dict[str, Any]:
    tracked = iter_tracked_files(root)
    by_ext: dict[str, int] = {}
    file_rows: list[dict[str, Any]] = []
    total = py = tests = scripts = demo = docs_md = 0
    for p in tracked:
        rel = p.relative_to(root)
        lines = _count_file_lines(p)
        total += lines
        ext = p.suffix.lower() or "<no_ext>"
        by_ext[ext] = by_ext.get(ext, 0) + lines
        if ext == ".py":
            py += lines
        if rel.parts and rel.parts[0] == "tests":
            tests += lines
        if rel.parts and rel.parts[0] == "scripts":
            scripts += lines
        if rel.parts and rel.parts[0] == "demo":
            demo += lines
        if ext == ".md" or (rel.parts and rel.parts[0] == "docs"):
            docs_md += lines
        file_rows.append({"file": str(rel), "lines": lines})
    file_rows.sort(key=lambda x: x["lines"], reverse=True)
    return {
        "total_lines": total,
        "python_lines": py,
        "tests_lines": tests,
        "scripts_lines": scripts,
        "demo_lines": demo,
        "docs_md_lines": docs_md,
        "lines_by_extension": dict(sorted(by_ext.items(), key=lambda x: x[0])),
        "top_files": file_rows[:10],
    }


def inspect_assets(root: Path) -> dict[str, Any]:
    test_files = (
        list((root / "tests").glob("test_*.py")) if (root / "tests").exists() else []
    )
    return {
        "tests_dir_exists": (root / "tests").is_dir(),
        "test_file_count": len(test_files),
        "pytest_collected_tests": "not_collected",
        "run_regression_gate_exists": (
            root / "scripts/run_regression_gate.py"
        ).is_file(),
        "ci_workflow_exists": (root / ".github/workflows/ci.yml").is_file(),
        "check_project_safety_exists": (
            root / "scripts/check_project_safety.py"
        ).is_file(),
        "export_submission_exists": (root / "scripts/export_submission.py").is_file(),
        "evaluate_results_exists": (root / "scripts/evaluate_results.py").is_file(),
        "replay_trace_exists": (root / "scripts/replay_trace.py").is_file(),
        "demo_streamlit_exists": (root / "demo/streamlit_app.py").is_file(),
        "final_report_exists": (root / "docs/final_report.md").is_file(),
        "submission_checklist_exists": (
            root / "docs/submission_checklist.md"
        ).is_file(),
        "hard_mode_control": (
            "present"
            if all(
                [
                    (root / "src/math_agent/control/hard_mode.py").is_file(),
                    (root / "docs/hard_mode_control.md").is_file(),
                    (root / "tests/test_hard_mode_control.py").is_file(),
                ]
            )
            else "missing"
        ),
    }


def _contains_tokens(path: Path, tokens: list[str]) -> dict[str, bool]:
    if not path.is_file():
        return {t: False for t in tokens}
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {t: t in text for t in tokens}


def _contains_command_signatures(path: Path, tokens: list[str]) -> dict[str, bool]:
    """Detect command text in both shell-like and Python list literal forms."""
    if not path.is_file():
        return {t: False for t in tokens}
    text = path.read_text(encoding="utf-8", errors="ignore")

    matched: dict[str, bool] = {}
    for token in tokens:
        if token in text:
            matched[token] = True
            continue
        parts = [re.escape(p) for p in token.split()]
        pattern = r"[\s,\[\]\"']+".join(parts)
        matched[token] = re.search(pattern, text) is not None
    return matched


def inspect_ci(root: Path) -> dict[str, Any]:
    ci_path = root / ".github/workflows/ci.yml"
    gate_path = root / "scripts/run_regression_gate.py"
    ci_tokens = [
        "ruff",
        "black",
        "isort",
        "mypy",
        "pyright",
        "pytest",
        "check_project_safety.py",
        "--no-trace",
    ]
    gate_tokens = [
        "ruff check .",
        "black --check",
        "isort --check-only",
        "mypy",
        "pyright",
        "pytest",
        "check_project_safety.py",
        "--no-trace",
        "scripts/shadow_eval.py",
        "scripts/build_eval_report.py",
        "--include-shadow-eval",
        "--mock",
        "--limit 5",
        "outputs/shadow_eval_gate/shadow_results.jsonl",
    ]
    gate_found = _contains_command_signatures(gate_path, gate_tokens)
    shadow_supported = all(
        gate_found.get(token, False)
        for token in [
            "scripts/shadow_eval.py",
            "scripts/build_eval_report.py",
            "--include-shadow-eval",
            "--mock",
            "--no-trace",
        ]
    ) and ("--real" not in gate_path.read_text(encoding="utf-8", errors="ignore"))
    return {
        "ci_status": "present" if ci_path.is_file() else "missing",
        "local_regression_gate": "present" if gate_path.is_file() else "missing",
        "recommended_command": "python scripts/run_regression_gate.py",
        "ci_contains": _contains_tokens(ci_path, ci_tokens),
        "gate_contains": gate_found,
        "gate_contains_real_flag": (
            "--real" in gate_path.read_text(encoding="utf-8", errors="ignore")
            if gate_path.is_file()
            else False
        ),
        "shadow_eval_gate": "supported" if shadow_supported else "missing",
    }


def inspect_risks(root: Path) -> dict[str, Any]:
    traces_files = []
    for folder in [
        root / "outputs/traces",
        root / "outputs/trace",
        root / "trace",
        root / "traces",
    ]:
        if folder.exists():
            traces_files.extend(
                [
                    str(p.relative_to(root))
                    for p in folder.rglob("*")
                    if p.is_file() and p.name != ".gitkeep"
                ]
            )
    risk = {
        "env_exists": (root / ".env").is_file(),
        "env_glob_exists": bool(list(root.glob(".env.*"))),
        "trace_files_exist": bool(traces_files),
        "trace_files": traces_files,
        "outputs_jsonl_exists": (
            bool(list((root / "outputs").glob("*.jsonl")))
            if (root / "outputs").exists()
            else False
        ),
        "outputs_run_records_exists": (root / "outputs/run_records").exists(),
        "trace_dir_exists": (root / "trace").exists(),
        "run_records_dir_exists": (root / "run_records").exists(),
        "pycache_exists": bool(list(root.rglob("__pycache__"))),
        "pytest_cache_exists": (root / ".pytest_cache").exists(),
        "submission_zip_exists": (root / "submission.zip").is_file(),
        "gitignore_exists": (root / ".gitignore").is_file(),
        "env_example_exists": (root / ".env.example").is_file(),
    }
    risk["p0_risks"] = [
        name
        for name, bad in {
            "runtime_traces_present": risk["trace_files_exist"],
            "env_file_present": risk["env_exists"],
            "outputs_jsonl_present": risk["outputs_jsonl_exists"],
        }.items()
        if bad
    ]
    return risk


def collect_pytest_count(root: Path) -> dict[str, Any]:
    res = run_cmd(
        ["python", "-m", "pytest", "--collect-only", "-q"], timeout=60, cwd=root
    )
    if not res["ok"]:
        return {
            "pytest_collected_tests": "unknown",
            "collect_error": (res["stderr"] or res["stdout"])[:300],
        }
    lines = [x for x in res["stdout"].splitlines() if x.strip()]
    count_line = next(
        (
            x
            for x in reversed(lines)
            if "test" in x.lower() and "collected" in x.lower()
        ),
        "",
    )
    count = "unknown"
    if count_line:
        digits = "".join(ch if ch.isdigit() else " " for ch in count_line).split()
        if digits:
            count = int(digits[0])
    return {"pytest_collected_tests": count, "collect_error": ""}


def compute_health_score(report: dict[str, Any]) -> dict[str, Any]:
    assets, ci, risks = report["assets"], report["ci"], report["risks"]
    score = 0
    score += 10 if assets["tests_dir_exists"] else 0
    score += 10 if assets["test_file_count"] >= 10 else 0
    score += 15 if assets["run_regression_gate_exists"] else 0
    score += 15 if assets["ci_workflow_exists"] else 0
    score += (
        15 if ci["ci_contains"].get("mypy") and ci["ci_contains"].get("pyright") else 0
    )
    score += 10 if assets["check_project_safety_exists"] else 0
    score += 5 if assets["final_report_exists"] else 0
    score += 5 if assets["submission_checklist_exists"] else 0
    score += 5 if assets["demo_streamlit_exists"] else 0
    score += 10 if not risks["p0_risks"] else 0
    if score >= 90:
        grade = "strong engineering baseline"
    elif score >= 75:
        grade = "solid competition baseline"
    elif score >= 60:
        grade = "usable but needs hardening"
    else:
        grade = "fragile"
    return {
        "health_score": score,
        "grade": grade,
        "note": "This is not an official competition score.",
    }


def next_steps(report: dict[str, Any]) -> dict[str, list[str]]:
    p0: list[str] = []
    p1: list[str] = []
    p2: list[str] = []
    if report["ci"]["ci_status"] == "missing":
        p0.append("add CI workflow")
    if report["ci"]["local_regression_gate"] == "missing":
        p0.append("add local gate runner")
    if report["risks"]["trace_files_exist"]:
        p0.append("clean runtime traces")
    if report["risks"]["env_exists"]:
        p0.append("ensure .env is ignored and not committed")
    if not report["assets"]["final_report_exists"]:
        p1.append("add report skeleton")
    if not report["assets"]["submission_checklist_exists"]:
        p1.append("add submission checklist")
    if not report["assets"]["demo_streamlit_exists"]:
        p2.append("add demo entry")
    return {"P0": p0, "P1": p1, "P2": p2}


def render_markdown(report: dict[str, Any], include_file_table: bool = False) -> str:
    lines = ["# Project Health Report", ""]
    lines += ["## 1. Git 状态"]
    git = report["git"]
    lines += [
        f"- branch: {git['branch']}",
        f"- commit_short: {git['commit_short']}",
        f"- git_status_clean: {git['git_status_clean']}",
        f"- has_uncommitted_changes: {git['has_uncommitted_changes']}",
        f"- remote: {git['remote']}",
        "- recent_commits:",
    ]
    lines += (
        [f"  - {c}" for c in git["recent_commits"]]
        if git["recent_commits"]
        else ["  - unknown"]
    )
    lines += ["", "## 2. 代码规模"]
    size = report["size"]
    for k in [
        "total_lines",
        "python_lines",
        "tests_lines",
        "scripts_lines",
        "demo_lines",
        "docs_md_lines",
    ]:
        lines.append(f"- {k}: {size[k]}")
    lines.append("- lines_by_extension:")
    for ext, cnt in size["lines_by_extension"].items():
        lines.append(f"  - {ext}: {cnt}")
    if include_file_table:
        lines += ["- top_files:"] + [
            f"  - {row['file']}: {row['lines']}" for row in size["top_files"]
        ]
    lines += ["", "## 3. 测试与门禁资产"]
    for k, v in report["assets"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## 4. CI 与本地门禁状态提示"]
    ci = report["ci"]
    lines += [
        f"- CI status: {ci['ci_status']}",
        f"- local regression gate: {ci['local_regression_gate']}",
        f"- Shadow Eval Gate: {ci['shadow_eval_gate']}",
        f"- recommended command: {ci['recommended_command']}",
        f"- gate_contains_real_flag: {ci['gate_contains_real_flag']}",
    ]
    lines += ["", "## 5. 安全与提交污染风险"]
    for k, v in report["risks"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## 6. 项目成熟度评分"]
    lines += [
        f"- health_score: {report['score']['health_score']}/100",
        f"- grade: {report['score']['grade']}",
        f"- note: {report['score']['note']}",
    ]
    lines += ["", "## 7. 下一步建议"]
    for lvl in ["P0", "P1", "P2"]:
        items = report["next_steps"][lvl]
        lines.append(f"- {lvl}: {'; '.join(items) if items else 'none'}")
    return "\n".join(lines) + "\n"


def build_report(root: Path, collect_tests: bool) -> dict[str, Any]:
    report = {
        "git": get_git_info(root),
        "size": count_lines(root),
        "assets": inspect_assets(root),
        "ci": inspect_ci(root),
        "risks": inspect_risks(root),
    }
    if collect_tests:
        report["assets"].update(collect_pytest_count(root))
    report["score"] = compute_health_score(report)
    report["next_steps"] = next_steps(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only project health report generator"
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--collect-tests", action="store_true")
    parser.add_argument("--include-file-table", action="store_true")
    parser.add_argument("--fail-on-risk", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    root = args.root.resolve()
    report = build_report(root, collect_tests=args.collect_tests)
    output = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_markdown(report, include_file_table=args.include_file_table)
    )

    if args.output:
        safe_text_write(output, args.output)
    else:
        print(output)

    if args.fail_on_risk and report["risks"]["p0_risks"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
