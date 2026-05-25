from __future__ import annotations

from pathlib import Path

from math_agent.debugger.failure_attribution import DebuggerReport
from math_agent.debugger.root_cause import infer_root_cause, infer_severity


def render_failure_debug_report(report: DebuggerReport) -> str:
    lines = [
        "# Agent Debugger Report",
        "",
        "This is NOT official evaluation.",
        "This report is derived from mock / preofficial / shadow evaluation outputs.",
        "Do not claim official accuracy from this report.",
        "",
        "## 1. Summary",
        f"- total: {report.total}",
        f"- failed_count: {report.failed_count}",
        f"- pass_count: {report.pass_count}",
        "## 2. Failure Category Counts",
        str(report.failure_category_counts),
        "## 3. Domain Failure Counts",
        str(report.domain_failure_counts),
        "## 4. Difficulty Failure Counts",
        str(report.difficulty_failure_counts),
        "## 5. Answer Type Failure Counts",
        str(report.answer_type_failure_counts),
        "## 6. Failure Clusters",
    ]
    lines.extend(
        [
            f"- {c.key}: {c.count} ({c.severity}) owner={c.suggested_owner}"
            for c in report.clusters
        ]
    )
    lines.append("## 7. Representative Failures")
    lines.extend(
        [
            f"- {c.id}: {c.failure_category} status={c.status}"
            for c in report.representative_failures
        ]
    )
    lines.append("## 8. Root Cause Mapping")
    lines.extend(
        [
            f"- {c.id}: {infer_root_cause(c).root_cause}"
            for c in report.representative_failures
        ]
    )
    lines.append("## 9. P0 Actions")
    lines.extend([f"- {a}" for a in report.p0_actions] or ["- none"])
    lines.append("## 10. P1 Actions")
    lines.extend([f"- {a}" for a in report.p1_actions] or ["- none"])
    lines.append("## 11. P2 Actions")
    lines.extend([f"- {a}" for a in report.p2_actions] or ["- none"])
    lines.extend(
        [
            "## 12. Official Submission Warning",
            "- This debugger output is not official scoring.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_demo_case_list(report: DebuggerReport) -> str:
    def _pick(categories: set[str]) -> list[str]:
        items = [
            c
            for c in report.representative_failures
            if c.failure_category in categories
        ]
        return [
            f"- id={c.id} domain={c.domain} difficulty={c.difficulty} "
            f"failure_category={c.failure_category} suggested demo angle="
            f"{infer_severity(c)}-{infer_root_cause(c).owner}"
            for c in items[:3]
        ]

    lines = [
        "# Demo Cases (Shadow/Mock Only)",
        "This is not official evaluation.",
        "",
        "## Top 3 format failures",
        *(
            _pick(
                {
                    "json_invalid",
                    "missing_final",
                    "dirty_boxed",
                    "boxed_42_fallback",
                    "formatter_repair_failed",
                }
            )
            or ["- none"]
        ),
        "## Top 3 wrong answer failures",
        *(_pick({"wrong_answer"}) or ["- none"]),
        "## Top 3 proof/tool/verifier failures",
        *(_pick({"proof_partial", "tool_error", "verifier_failed"}) or ["- none"]),
    ]
    return "\n".join(lines) + "\n"


def write_markdown(path: Path | str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
