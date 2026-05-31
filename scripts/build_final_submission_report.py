from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from math_agent.harness.lagent_trace_adapter import lagent_alignment_evidence_table

OFFICIAL_WARNING = (
    "This is NOT official evaluation. Do not claim official hidden-set accuracy "
    "from this report."
)


def _read_json(path: str | Path | None, default: Any) -> Any:
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ") or "missing"


def _metric(summary: dict[str, Any], key: str) -> Any:
    return summary.get(key, "missing") if summary else "missing"


def _real_api_status(summary: dict[str, Any]) -> str:
    if not summary:
        return "missing"
    if int(summary.get("total_model_calls") or 0) <= 0:
        return "blocked_or_not_executed"
    if int(summary.get("fail_count") or 0) > 0:
        return "needs_failure_closure"
    return "passed"


def _render_metrics(summary: dict[str, Any]) -> list[str]:
    keys = [
        "preflight",
        "sample_count",
        "domain_count",
        "pass_count",
        "partial_count",
        "fail_count",
        "pass_rate",
        "total_model_calls",
        "total_tool_calls",
        "tool_solved_count",
        "model_solved_count",
        "model_verified_count",
        "average_latency_seconds",
    ]
    lines = ["| Metric | Value |", "|---|---:|"]
    for key in keys:
        lines.append(f"| {key} | {_cell(_metric(summary, key))} |")
    return lines


def _render_domain_rows(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Domain | Samples | Pass | Partial | Fail | Proof Risks | Model Calls | Tool Calls | Failures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    if not rows:
        lines.append("| missing | 0 | 0 | 0 | 0 | 0 | 0 | 0 | missing |")
        return lines
    for row in rows:
        failures = ", ".join(str(x) for x in row.get("failure_question_ids", []))
        lines.append(
            "| {domain} | {sample_count} | {pass_count} | {partial_count} | {fail_count} | {proof_risk_count} | {model_calls} | {tool_calls} | {failures} |".format(
                domain=_cell(row.get("domain")),
                sample_count=_cell(row.get("sample_count")),
                pass_count=_cell(row.get("pass_count")),
                partial_count=_cell(row.get("partial_count")),
                fail_count=_cell(row.get("fail_count")),
                proof_risk_count=_cell(row.get("proof_risk_count")),
                model_calls=_cell(row.get("model_calls")),
                tool_calls=_cell(row.get("tool_calls")),
                failures=_cell(failures or "none"),
            )
        )
    return lines


def _render_failure_buckets(rows: list[dict[str, Any]]) -> list[str]:
    counts = Counter(
        str(row.get("review_bucket") or row.get("suggested_fix_category") or "unknown")
        for row in rows
    )
    lines = ["| Review Bucket | Count |", "|---|---:|"]
    if not counts:
        lines.append("| none | 0 |")
        return lines
    for bucket, count in sorted(counts.items()):
        lines.append(f"| {_cell(bucket)} | {count} |")
    return lines


def _render_lagent_rows() -> list[str]:
    lines = ["| Project Stage | lagent Concept | Evidence |", "|---|---|---|"]
    for row in lagent_alignment_evidence_table():
        lines.append(
            "| {stage} | {concept} | {evidence} |".format(
                stage=_cell(row.get("project_stage")),
                concept=_cell(row.get("lagent_concept")),
                evidence=_cell(row.get("review_evidence")),
            )
        )
    return lines


def _render_reviewer_evidence_rows() -> list[str]:
    return [
        "| Evidence Item | Local Source | Status | Notes |",
        "|---|---|---|---|",
        "| Real API sample summary | `outputs/real_api_sample_gate/real_api_sample_gate_summary.json` | local-only | pass/fail/partial, latency, model_calls, tool_calls |",
        "| Failure closure table | `outputs/real_api_sample_gate/failure_replay_report.md` | local-only | review bucket and rerun outcome for fixed failures |",
        "| lagent alignment table | this report / `docs/lagent_alignment.md` | included | Planner/Solver/Verifier/Tool Observation mapping |",
        "| Safety gate evidence | terminal / CI page | required before packaging | cleanup + `check_project_safety.py` PASS |",
        "| Quality gate evidence | terminal / CI page | required before packaging | `run_regression_gate.py` PASS after dev tools are installed |",
    ]


def _render_gate_environment(report: dict[str, Any]) -> list[str]:
    if not report:
        return [
            "| Check | Value |",
            "|---|---|",
            "| ready_for_regression_gate | missing |",
            "| ready_for_real_api_env | missing |",
            "| ready_for_real_api_gate | missing |",
        ]
    lines = [
        "| Check | Value |",
        "|---|---|",
        f"| ready_for_regression_gate | {_cell(report.get('ready_for_regression_gate'))} |",
        f"| ready_for_real_api_env | {_cell(report.get('ready_for_real_api_env'))} |",
        f"| ready_for_real_api_gate | {_cell(report.get('ready_for_real_api_gate'))} |",
    ]
    missing_tools = report.get("missing_dev_tools") or []
    lines.append(f"| missing_dev_tools | {_cell(', '.join(missing_tools) or 'none')} |")
    real_api_raw = report.get("real_api")
    real_api: dict[str, Any] = real_api_raw if isinstance(real_api_raw, dict) else {}
    lines.append(f"| real_api_preflight | {_cell(real_api.get('preflight'))} |")
    lines.append(f"| has_api_key | {_cell(real_api.get('has_api_key'))} |")
    lines.append(f"| has_base_url | {_cell(real_api.get('has_base_url'))} |")
    return lines


def _gate_environment_status(report: dict[str, Any]) -> str:
    if not report:
        return "missing"
    if report.get("ready_for_regression_gate") and report.get(
        "ready_for_real_api_gate"
    ):
        return "ready"
    if report.get("ready_for_real_api_env") and not report.get(
        "ready_for_real_api_gate"
    ):
        return "needs_real_api_preflight"
    return "needs_setup"


def render_final_submission_report(
    *,
    real_api_summary: dict[str, Any],
    domain_dashboard: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
    gate_environment: dict[str, Any] | None = None,
) -> str:
    real_status = _real_api_status(real_api_summary)
    gate_environment = gate_environment or {}
    gate_status = _gate_environment_status(gate_environment)
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    sections = [
        "# Final Submission Evidence Report",
        "",
        OFFICIAL_WARNING,
        "",
        "## 1. Stage Status",
        "",
        f"- generated_at_utc: {generated_at}",
        f"- real_api_status: {real_status}",
        f"- gate_environment_status: {gate_status}",
        "- stable_runtime_changed: no",
        "- raw_outputs_committed: no",
        "",
        "## 2. Gate Commands",
        "",
        "| Command | Expected Evidence |",
        "|---|---|",
        "| `python -m pytest -q` | all tests pass |",
        "| `python scripts/run_regression_gate.py` | local lint/type/test gate |",
        "| `python scripts/run_pre_submit_gate.py --dry-run-limit 3` | pytest + mock official-style dry-run + cleanup + safety |",
        "| `python scripts/check_project_safety.py` | no secret/output/cache pollution |",
        "| `python scripts/run_real_api_sample_gate.py ... --real --allow-real` | opt-in real API sample gate |",
        "",
        "## 3. Gate Environment Readiness",
        "",
        *_render_gate_environment(gate_environment),
        "",
        "## 4. Real API Metrics",
        "",
        *_render_metrics(real_api_summary),
        "",
        "## 5. 18-Domain Dashboard",
        "",
        *_render_domain_rows(domain_dashboard),
        "",
        "## 6. Failure Closure Buckets",
        "",
        *_render_failure_buckets(failure_rows),
        "",
        "## 7. lagent Alignment Evidence",
        "",
        *_render_lagent_rows(),
        "",
        "## 8. Final Reviewer Evidence",
        "",
        *_render_reviewer_evidence_rows(),
        "",
        "## 9. Submission Boundary",
        "",
        "- No `.env`, API key, Authorization header, or Bearer token is included.",
        "- No `outputs/`, `trace/`, `traces/`, `run_records/`, `official_results.jsonl`, `submission.zip`, cache, or build artifact should be packaged.",
        "- `official_style_*` data is synthetic official-style regression data, not official hidden-set data.",
        "- Real API raw traces stay local and must be cleaned before final packaging.",
    ]
    return "\n".join(sections) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a final/stage submission evidence report from local summaries."
    )
    parser.add_argument("--out-dir", default="outputs/final_submission_report")
    parser.add_argument(
        "--real-api-summary",
        default="outputs/real_api_sample_gate/real_api_sample_gate_summary.json",
    )
    parser.add_argument(
        "--domain-dashboard",
        default="outputs/real_api_sample_gate/domain_dashboard.json",
    )
    parser.add_argument(
        "--failure-report",
        default="outputs/real_api_sample_gate/failure_replay_report.json",
    )
    parser.add_argument(
        "--gate-environment",
        default="outputs/gate_environment/gate_environment_report.json",
    )
    parser.add_argument(
        "--fail-on-missing-real-api",
        action="store_true",
        help="Exit non-zero unless a real API summary exists and total_model_calls > 0.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    real_api_summary = _read_json(args.real_api_summary, {})
    domain_dashboard = _read_json(args.domain_dashboard, [])
    failure_rows = _read_json(args.failure_report, [])
    gate_environment = _read_json(args.gate_environment, {})
    if not isinstance(real_api_summary, dict):
        real_api_summary = {}
    if not isinstance(domain_dashboard, list):
        domain_dashboard = []
    if not isinstance(failure_rows, list):
        failure_rows = []
    if not isinstance(gate_environment, dict):
        gate_environment = {}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = render_final_submission_report(
        real_api_summary=real_api_summary,
        domain_dashboard=domain_dashboard,
        failure_rows=failure_rows,
        gate_environment=gate_environment,
    )
    report_path = out_dir / "final_submission_report.md"
    report_path.write_text(report, encoding="utf-8")
    inputs_path = out_dir / "final_submission_report_inputs.json"
    inputs_path.write_text(
        json.dumps(
            {
                "real_api_summary": args.real_api_summary,
                "domain_dashboard": args.domain_dashboard,
                "failure_report": args.failure_report,
                "gate_environment": args.gate_environment,
                "real_api_status": _real_api_status(real_api_summary),
                "gate_environment_status": _gate_environment_status(gate_environment),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"report={report_path}")
    print(f"real_api_status={_real_api_status(real_api_summary)}")
    if args.fail_on_missing_real_api and _real_api_status(real_api_summary) in {
        "missing",
        "blocked_or_not_executed",
    }:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
