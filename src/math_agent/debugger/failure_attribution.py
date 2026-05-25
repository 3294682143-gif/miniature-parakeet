from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from math_agent.debugger.root_cause import infer_root_cause, infer_severity


@dataclass
class FailureCase:
    id: str
    question: str
    expected_answer: str | None
    predicted_answer: str
    domain: str
    difficulty: str
    answer_type: str
    failure_category: str
    exact_match: bool
    status: str
    error_message: str
    raw: dict[str, Any]


@dataclass
class FailureCluster:
    key: str
    count: int
    case_ids: list[str]
    domains: dict[str, int]
    difficulties: dict[str, int]
    answer_types: dict[str, int]
    representative_ids: list[str]
    severity: str
    suggested_owner: str
    suggested_next_action: str


@dataclass
class DebuggerReport:
    total: int
    failed_count: int
    pass_count: int
    failure_category_counts: dict[str, int]
    domain_failure_counts: dict[str, int]
    difficulty_failure_counts: dict[str, int]
    answer_type_failure_counts: dict[str, int]
    clusters: list[FailureCluster]
    representative_failures: list[FailureCase]
    p0_actions: list[str]
    p1_actions: list[str]
    p2_actions: list[str]


def _to_case(row: dict[str, Any], idx: int) -> FailureCase:
    return FailureCase(
        id=str(row.get("id", f"row-{idx:04d}")),
        question=str(row.get("question", "")),
        expected_answer=(
            None
            if row.get("expected_answer") is None
            else str(row.get("expected_answer"))
        ),
        predicted_answer=str(row.get("predicted_answer", "")),
        domain=str(row.get("domain", "unknown")),
        difficulty=str(row.get("difficulty", "unknown")),
        answer_type=str(row.get("answer_type", "text")),
        failure_category=str(row.get("failure_category", "unknown")),
        exact_match=bool(row.get("exact_match", False)),
        status=str(row.get("status", "unknown")),
        error_message=str(row.get("error_message", "")),
        raw=row,
    )


def load_shadow_results(path: Path | str) -> list[FailureCase]:
    rows: list[FailureCase] = []
    p = Path(path)
    for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            rows.append(_to_case(obj if isinstance(obj, dict) else {}, idx))
        except json.JSONDecodeError as exc:
            rows.append(
                FailureCase(
                    id=f"malformed-{idx:04d}",
                    question="",
                    expected_answer=None,
                    predicted_answer="",
                    domain="unknown",
                    difficulty="unknown",
                    answer_type="text",
                    failure_category="malformed_json",
                    exact_match=False,
                    status="fail",
                    error_message=f"JSONDecodeError: {str(exc)[:120]}",
                    raw={"line": line},
                )
            )
    return rows


def _is_failure(case: FailureCase) -> bool:
    r = case.raw
    return (
        (case.expected_answer is not None and not case.exact_match)
        or case.failure_category != "ok"
        or case.status in {"fail", "exception", "timeout"}
        or r.get("json_valid") is False
        or r.get("final_answer_exists") is False
        or r.get("dirty_boxed") is True
        or r.get("boxed_42_fallback") is True
        or r.get("verifier_passed") is False
    )


def filter_failures(cases: list[FailureCase]) -> list[FailureCase]:
    return [c for c in cases if _is_failure(c)]


def cluster_failures(cases: list[FailureCase]) -> list[FailureCluster]:
    grouped: dict[str, list[FailureCase]] = defaultdict(list)
    for c in cases:
        grouped[c.failure_category].append(c)
    out: list[FailureCluster] = []
    for key, group in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        info = infer_root_cause(group[0])
        out.append(
            FailureCluster(
                key=key,
                count=len(group),
                case_ids=[g.id for g in group],
                domains=dict(Counter(g.domain for g in group)),
                difficulties=dict(Counter(g.difficulty for g in group)),
                answer_types=dict(Counter(g.answer_type for g in group)),
                representative_ids=[g.id for g in group[:3]],
                severity=infer_severity(group[0]),
                suggested_owner=info.owner,
                suggested_next_action=info.action,
            )
        )
    return out


def select_representatives(
    cases: list[FailureCase], limit: int = 10
) -> list[FailureCase]:
    ranked = sorted(cases, key=lambda c: (infer_severity(c), c.failure_category, c.id))
    return ranked[: max(0, limit)]


def build_debugger_report(cases: list[FailureCase]) -> DebuggerReport:
    failures = filter_failures(cases)
    clusters = cluster_failures(failures)
    actions: dict[str, set[str]] = {"P0": set(), "P1": set(), "P2": set()}
    for c in failures:
        sev = infer_severity(c)
        info = infer_root_cause(c)
        if sev in actions:
            actions[sev].add(
                f"[{c.failure_category}] owner={info.owner}: {info.action}"
            )
    return DebuggerReport(
        total=len(cases),
        failed_count=len(failures),
        pass_count=len(cases) - len(failures),
        failure_category_counts=dict(Counter(c.failure_category for c in failures)),
        domain_failure_counts=dict(Counter(c.domain for c in failures)),
        difficulty_failure_counts=dict(Counter(c.difficulty for c in failures)),
        answer_type_failure_counts=dict(Counter(c.answer_type for c in failures)),
        clusters=clusters,
        representative_failures=select_representatives(failures),
        p0_actions=sorted(actions["P0"]),
        p1_actions=sorted(actions["P1"]),
        p2_actions=sorted(actions["P2"]),
    )


def write_debugger_outputs(report: DebuggerReport, out_dir: Path | str) -> None:
    from math_agent.debugger.report import (
        render_demo_case_list,
        render_failure_debug_report,
        write_markdown,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_markdown(out / "failure_debug_report.md", render_failure_debug_report(report))
    write_markdown(out / "demo_cases.md", render_demo_case_list(report))
    (out / "failure_clusters.json").write_text(
        json.dumps([asdict(c) for c in report.clusters], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (out / "root_causes.json").write_text(
        json.dumps(
            [
                {
                    **asdict(c),
                    "root_cause": asdict(infer_root_cause(c)),
                    "severity": infer_severity(c),
                }
                for c in report.representative_failures
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
