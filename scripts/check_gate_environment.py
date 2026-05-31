from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from math_agent.clients.interns1_client import InternS1Client
from scripts.run_real_api_sample_gate import _run_real_preflight

DEV_TOOLS = {
    "ruff": "ruff",
    "black": "black",
    "isort": "isort",
    "mypy": "mypy",
    "pyright": "pyright",
}


def inspect_dev_tools() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool, module in DEV_TOOLS.items():
        rows.append(
            {
                "tool": tool,
                "module": module,
                "module_available": importlib.util.find_spec(module) is not None,
                "command_path": shutil.which(tool) or "",
            }
        )
    return rows


def inspect_real_api_env(run_preflight: bool) -> dict[str, Any]:
    env = {
        "has_api_key": bool(os.getenv("INTERNS1_API_KEY")),
        "has_base_url": bool(os.getenv("INTERNS1_BASE_URL")),
        "has_model": bool(os.getenv("INTERNS1_MODEL")),
        "preflight": "skipped",
        "preflight_message": "",
    }
    if run_preflight:
        ok, message = _run_real_preflight(InternS1Client(mock=False))
        env["preflight"] = "passed" if ok else "failed"
        env["preflight_message"] = message
    return env


def build_environment_report(run_preflight: bool) -> dict[str, Any]:
    dev_tools = inspect_dev_tools()
    missing_dev_tools = [
        row["tool"]
        for row in dev_tools
        if not row["module_available"] and not row["command_path"]
    ]
    real_api = inspect_real_api_env(run_preflight=run_preflight)
    ready_for_real_api_env = bool(real_api["has_api_key"]) and bool(
        real_api["has_base_url"]
    )
    return {
        "python": sys.executable,
        "dev_tools": dev_tools,
        "missing_dev_tools": missing_dev_tools,
        "real_api": real_api,
        "ready_for_regression_gate": not missing_dev_tools,
        "ready_for_real_api_env": ready_for_real_api_env,
        "ready_for_real_api_gate": ready_for_real_api_env
        and real_api["preflight"] == "passed",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Gate Environment Report",
        "",
        "This report does not print API keys, tokens, Authorization headers, or Bearer values.",
        "",
        f"- python: `{report['python']}`",
        f"- ready_for_regression_gate: {report['ready_for_regression_gate']}",
        f"- ready_for_real_api_env: {report['ready_for_real_api_env']}",
        f"- ready_for_real_api_gate: {report['ready_for_real_api_gate']}",
        "",
        "## Dev Tools",
        "",
        "| Tool | Python module | Command path | Status |",
        "|---|---|---|---|",
    ]
    for row in report["dev_tools"]:
        status = "PASS" if row["module_available"] or row["command_path"] else "MISSING"
        command_path = row["command_path"] or "missing"
        lines.append(
            f"| {row['tool']} | {row['module_available']} | `{command_path}` | {status} |"
        )
    lines.extend(
        [
            "",
            "## Real API Environment",
            "",
            f"- has_api_key: {report['real_api']['has_api_key']}",
            f"- has_base_url: {report['real_api']['has_base_url']}",
            f"- has_model: {report['real_api']['has_model']}",
            f"- preflight: {report['real_api']['preflight']}",
            f"- preflight_message: {report['real_api']['preflight_message'] or 'none'}",
            "",
            "## Recommended Commands",
            "",
            "```bash",
            "python -m pip install -e .[dev] ruff black isort mypy pyright",
            "python scripts/run_regression_gate.py",
            "python scripts/check_gate_environment.py --out-dir outputs/gate_environment --real --allow-real",
            "python scripts/run_real_api_sample_gate.py --input data/official_style_18domain_112.jsonl --answers data/official_style_18domain_112_answers.jsonl --out-dir outputs/real_api_sample_gate --per-domain 2 --real --allow-real --max-attempts 2",
            "python scripts/build_final_submission_report.py --out-dir outputs/final_submission_report --fail-on-missing-real-api",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check local gate tooling and real API environment without leaking secrets."
    )
    parser.add_argument("--out-dir", default="outputs/gate_environment")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--real", action="store_true", default=False)
    parser.add_argument("--allow-real", action="store_true", default=False)
    parser.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit non-zero if dev tools or required real API env are missing.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_preflight = bool(args.real and args.allow_real)
    if args.real and not args.allow_real:
        print(
            "real API preflight requires explicit --real --allow-real", file=sys.stderr
        )
        return 2
    report = build_environment_report(run_preflight=run_preflight)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "gate_environment_report.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path = out_dir / "gate_environment_report.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"report={md_path if args.format == 'markdown' else json_path}")
    print(f"ready_for_regression_gate={report['ready_for_regression_gate']}")
    print(f"ready_for_real_api_gate={report['ready_for_real_api_gate']}")
    if args.fail_on_missing and (
        not report["ready_for_regression_gate"] or not report["ready_for_real_api_gate"]
    ):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
