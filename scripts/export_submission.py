from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

from check_project_safety import scan_project


EXCLUDE_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
}

EXCLUDE_FILE_PATTERNS = (
    ".env",
    ".env.",
)


def _is_excluded_name(name: str) -> bool:
    return name == ".env" or name.startswith(".env.")


def _safe_copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _safe_copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
            continue
        if _is_excluded_name(path.name):
            continue
        if path.is_dir():
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _write_readme_submission(target: Path, has_report: bool, has_demo: bool, report_name: str) -> None:
    content = f"""# EvoExternMath-S1++ Frozen Submission

## 1. Frozen Harness 说明
本提交包面向 EvoExternMath-S1++ Frozen Submission，保持 stable pipeline 冻结基线，不修改核心求解流程与 CLI 行为。

## 2. 运行环境
- Python 3.10+
- 建议：Linux / macOS
- 依赖安装：`pip install -e \".[dev]\"`

## 3. 运行命令
- 单题：`python -m math_agent.cli solve --question \"计算 2+3\" --enable-tools`
- 批量：`python -m math_agent.cli batch --input data/official_questions.jsonl --output outputs/official_results.jsonl --enable-tools`
- 评测：`python scripts/evaluate_results.py --results outputs/official_results.jsonl --report outputs/official_evaluation_report.md`

## 4. JSON 输出格式
批量输出为 JSONL，每行一个 SolveResult，关键字段包括：`question_id`、`final_answer`、`status`、`error`、`verification`。

## 5. Trace 日志说明
trace 位于 `logs/traces/`，用于审计模型调用、工具调用、校验结果与错误记录。

## 6. 复现步骤
1. 准备输入题集（JSONL）。
2. 执行 batch 生成 `official_results.jsonl`。
3. 执行 evaluate 生成报告。
4. 使用 `scripts/export_submission.py` 打包 Frozen Submission。

## 7. 安全说明
- 提交包不包含 API key / `.env` / `.git` / 常见缓存目录。
- 如检测到疑似敏感信息（如 Authorization / Bearer token），导出流程将直接失败。
- 允许 `.env.example` 存在于项目源代码中，但不会被提交打包。

## 8. 提交内容说明
- report 包含状态：{"included" if has_report else "missing"}（期望文件名：`{report_name}`）
- demo 脚本状态：{"included" if has_demo else "missing"}
- `official_results.jsonl` 不应人工逐题修改。
"""
    target.write_text(content, encoding="utf-8")


def _run_safety_scan(repo_root: Path) -> list[tuple[str, str]]:
    findings = scan_project(repo_root)
    blocked: list[tuple[str, str]] = []
    ignored_risks = {
        "forbidden_outputs_jsonl",
        "forbidden_outputs_traces",
        "forbidden_outputs_run_records",
        "forbidden_submission_archive",
        "forbidden_env_file",
        "forbidden___pycache___artifact",
        "forbidden_.pytest_cache_artifact",
    }
    for rel_path, risk in findings:
        if risk in ignored_risks:
            continue
        blocked.append((rel_path, risk))
    return blocked


def _zip_directory(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(source_dir.parent)
            zf.write(path, arcname=str(rel))


def _print_warning(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export EvoExternMath-S1++ frozen submission package")
    parser.add_argument("--results", required=True, help="Path to official results jsonl")
    parser.add_argument("--traces", required=True, help="Path to traces directory")
    parser.add_argument("--report", required=True, help="Path to evaluation report")
    parser.add_argument("--run-record", required=True, help="Path to run record directory")
    parser.add_argument("--out", default="submission", help="Output directory")
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    results = (repo_root / args.results).resolve()
    traces = (repo_root / args.traces).resolve()
    report = (repo_root / args.report).resolve()
    run_record = (repo_root / args.run_record).resolve()
    out_dir = (repo_root / args.out).resolve()

    if not results.is_file():
        print(f"ERROR: results file not found: {args.results}", file=sys.stderr)
        return 2
    if not traces.is_dir():
        print(f"ERROR: traces directory not found: {args.traces}", file=sys.stderr)
        return 2

    findings = _run_safety_scan(repo_root)
    if findings:
        print("ERROR: high-risk sensitive content detected:", file=sys.stderr)
        for rel_path, risk in findings:
            print(f"- {risk}: {rel_path}", file=sys.stderr)
        return 3

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "result").mkdir(parents=True, exist_ok=True)
    (out_dir / "logs" / "traces").mkdir(parents=True, exist_ok=True)
    (out_dir / "logs" / "run_record").mkdir(parents=True, exist_ok=True)
    (out_dir / "report").mkdir(parents=True, exist_ok=True)
    (out_dir / "demo").mkdir(parents=True, exist_ok=True)
    (out_dir / "docs").mkdir(parents=True, exist_ok=True)

    _safe_copy_file(results, out_dir / "result" / "final_output.jsonl")
    _safe_copy_tree(traces, out_dir / "logs" / "traces")

    if run_record.is_dir():
        _safe_copy_tree(run_record, out_dir / "logs" / "run_record")
    else:
        _print_warning(f"run-record not found, skipped: {args.run_record}")

    report_included = False
    if report.is_file():
        suffix = report.suffix.lower()
        if suffix == ".pdf":
            report_name = "final_report.pdf"
        else:
            report_name = "final_report.md"
        _safe_copy_file(report, out_dir / "report" / report_name)
        report_included = True
    else:
        report_name = "final_report.md"
        _print_warning(f"report not found, skipped: {args.report}")

    demo_script_src = repo_root / "demo" / "demo_script.md"
    demo_included = demo_script_src.is_file()
    if demo_included:
        _safe_copy_file(demo_script_src, out_dir / "demo" / "demo_script.md")

    for doc_name in ("system_overview.md", "replay.md"):
        src = repo_root / doc_name
        if src.is_file():
            _safe_copy_file(src, out_dir / "docs" / doc_name)

    candidate_summary = repo_root / "candidate_summary.md"
    if candidate_summary.is_file():
        _safe_copy_file(candidate_summary, out_dir / "docs" / "candidate_summary.md")

    _write_readme_submission(out_dir / "docs" / "README_SUBMISSION.md", report_included, demo_included, report_name)

    snapshot_note = {
        "project": "EvoExternMath-S1++",
        "frozen_submission": True,
        "excluded": [".env", ".env.*", ".git", "__pycache__", ".pytest_cache", "outputs/debug*", "outputs/mock*", "outputs/local*"],
    }
    (out_dir / "src_snapshot_note.md").write_text(
        "# Source Snapshot Note\n\n```json\n" + json.dumps(snapshot_note, ensure_ascii=False, indent=2) + "\n```\n",
        encoding="utf-8",
    )

    _zip_directory(out_dir, repo_root / "submission.zip")
    print(f"OK: submission package created at {out_dir} and submission.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
