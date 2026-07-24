from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.clients.interns1_client import InternS1Client
from math_agent.evaluation.failure_report import (
    build_failure_rows,
    write_failure_report,
)
from math_agent.evaluation.metrics import evaluate_results, render_markdown_report
from math_agent.evaluation.proof_review import write_proof_review_pack
from math_agent.harness.trace_reader import read_trace
from math_agent.io_utils import (
    load_bounded_json,
    load_bounded_jsonl,
    path_is_within,
    paths_alias,
    read_bounded_utf8_text,
)
from math_agent.logging_utils import (
    atomic_text_write,
    ensure_dir,
    safe_text_write,
    trace_path_for_question,
)
from math_agent.pipeline import solve_question
from math_agent.schemas import MathQuestion, make_failure_result
from math_agent.security import safe_exception_text

_RETRYABLE_ERROR_SNIPPETS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection",
    "network",
    "network request failed",
    "rate limit",
    "429",
    "500",
    "502",
    "503",
    "504",
)
MAX_GATE_ATTEMPTS = 3
MAX_GATE_ITEMS = 1_000
MAX_RESULT_LINE_CHARS = 1_000_000
MAX_RESULTS_CHARS = 64 * 1024 * 1024
EXPECTED_DOMAINS = frozenset(
    {
        "Algebra",
        "Calculus",
        "Combinatorics",
        "ComplexAnalysis",
        "DifferentialEquations",
        "DiscreteMath",
        "FunctionalEquations",
        "Geometry",
        "LinearAlgebra",
        "NumberTheory",
        "NumericalAnalysis",
        "OperationsResearch",
        "Optimization",
        "PDE",
        "Probability",
        "RealAnalysis",
        "Statistics",
        "Topology",
    }
)


def _sample_coverage_ok(
    answer_rows: list[dict[str, Any]], *, per_domain: int, include_proof: bool
) -> bool:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in answer_rows:
        grouped[str(row.get("domain") or "unknown")].append(row)
    if not EXPECTED_DOMAINS.issubset(grouped):
        return False
    for domain in EXPECTED_DOMAINS:
        rows = grouped[domain]
        unique_ids = {
            str(row.get("question_id")) for row in rows if row.get("question_id")
        }
        if len(unique_ids) < per_domain:
            return False
        if include_proof and not any(
            str(row.get("evaluation_mode", "")).startswith("proof")
            or str(row.get("problem_type", "")).casefold() == "proof"
            for row in rows
        ):
            return False
    return True


def _trace_integrity_ok(metrics: dict[str, Any], sample_count: int) -> bool:
    return bool(
        metrics.get("trace_read_ok") is True
        and metrics.get("trace_count") == sample_count
        and metrics.get("trace_eligible_question_id_count") == sample_count
        and metrics.get("trace_error_count") == 0
        and metrics.get("trace_missing_question_id_count") == 0
        and metrics.get("trace_unmatched_count") == 0
        and metrics.get("trace_duplicate_question_id_count") == 0
        and metrics.get("trace_result_question_id_mismatch_count") == 0
        and metrics.get("trace_result_content_mismatch_count") == 0
        and metrics.get("trace_provenance_mismatch_count") == 0
        and metrics.get("trace_binding_integrity_ok") is True
    )


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows, _ = load_bounded_jsonl(path, require_objects=True)
    return rows


def _select_question_ids(
    answers: list[dict[str, Any]],
    per_domain: int,
    limit: int | None,
    include_proof: bool = False,
) -> set[str]:
    by_domain: dict[str, list[str]] = defaultdict(list)
    proof_by_domain: dict[str, str] = {}
    for row in answers:
        domain = str(row.get("domain") or "unknown")
        qid = str(row.get("question_id") or "")
        if qid and len(by_domain[domain]) < per_domain:
            by_domain[domain].append(qid)
        evaluation_mode = str(row.get("evaluation_mode") or "")
        problem_type = str(row.get("problem_type") or "")
        if (
            include_proof
            and qid
            and domain not in proof_by_domain
            and (evaluation_mode.startswith("proof") or problem_type == "proof")
        ):
            proof_by_domain[domain] = qid
    selected: list[str] = []
    for domain in sorted(by_domain):
        selected.extend(by_domain[domain])
        proof_qid = proof_by_domain.get(domain)
        if proof_qid and proof_qid not in selected:
            selected.append(proof_qid)
    if limit is not None:
        selected = selected[:limit]
    return set(selected)


def _failure_question_ids_from_report(path: str | Path) -> set[str]:
    report_path = Path(path)
    if not report_path.exists() and report_path.suffix != ".json":
        sibling = report_path.with_suffix(".json")
        if sibling.exists():
            report_path = sibling
    if not report_path.exists():
        raise FileNotFoundError(f"failure report not found: {path}")
    text = read_bounded_utf8_text(report_path)
    if report_path.suffix == ".json":
        rows = load_bounded_json(report_path)
        if not isinstance(rows, list):
            raise ValueError("failure report JSON must be a list of rows")
        return {
            str(row.get("question_id"))
            for row in rows
            if isinstance(row, dict) and row.get("question_id")
        }
    return {
        match.group(1).strip()
        for match in re.finditer(r"^## Case:\s+(.+?)\s*$", text, flags=re.MULTILINE)
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    atomic_text_write(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        path,
    )


def _run_real_preflight(client: Any) -> tuple[bool, str]:
    try:
        response = client.chat(
            messages=[
                {
                    "role": "user",
                    "content": "Return the single word OK for a connectivity check.",
                }
            ],
            temperature=0.0,
            top_p=1.0,
            max_tokens=4,
        )
    except ValueError as exc:
        return False, safe_exception_text(exc)
    except Exception:
        return False, "unknown_error: preflight failed"
    if not str(response).strip():
        return False, "invalid_response: empty preflight response"
    return True, "ok"


def _trace_model_call_count(trace_dir: Path, question_id: str) -> int:
    trace_path = trace_path_for_question(trace_dir, question_id)
    if not trace_path.exists():
        return 0
    loaded = read_trace(trace_path)
    if loaded.get("ok") is not True or not isinstance(loaded.get("trace"), dict):
        return 0
    trace = loaded["trace"]
    calls = trace.get("model_calls")
    return len(calls) if isinstance(calls, list) else 0


def _trace_budget(trace_dir: Path, question_id: str) -> dict[str, int]:
    trace_path = trace_path_for_question(trace_dir, question_id)
    if not trace_path.exists():
        return {"model_calls": 0, "tool_calls": 0}
    loaded = read_trace(trace_path)
    if loaded.get("ok") is not True or not isinstance(loaded.get("trace"), dict):
        return {"model_calls": 0, "tool_calls": 0}
    trace = loaded["trace"]
    model_calls = trace.get("model_calls")
    tool_calls = trace.get("tool_calls")
    return {
        "model_calls": len(model_calls) if isinstance(model_calls, list) else 0,
        "tool_calls": len(tool_calls) if isinstance(tool_calls, list) else 0,
    }


def _build_domain_dashboard(
    *,
    result_rows: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
    trace_dir: Path,
    proof_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    answer_by_id = {str(row.get("question_id")): row for row in answer_rows}
    proof_by_id = {str(row.get("question_id")): row for row in proof_rows}
    failure_by_id = {str(row.get("question_id")): row for row in failure_rows}
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in result_rows:
        qid = str(row.get("question_id", ""))
        answer = answer_by_id.get(qid, {})
        domain = str(answer.get("domain") or row.get("domain") or "unknown")
        by_domain[domain].append(row)

    dashboard: list[dict[str, Any]] = []
    for domain in sorted(by_domain):
        rows = by_domain[domain]
        status_counts = Counter(str(row.get("status", "unknown")) for row in rows)
        qids = [str(row.get("question_id", "")) for row in rows]
        budgets = [_trace_budget(trace_dir, qid) for qid in qids]
        proof_risk_count = sum(
            1 for qid in qids if proof_by_id.get(qid, {}).get("risk_flags")
        )
        failure_ids = [qid for qid in qids if qid in failure_by_id]
        tool_solved = sum(
            1
            for row, budget in zip(rows, budgets, strict=False)
            if str(row.get("status")) == "success" and budget["tool_calls"] > 0
        )
        model_solved = sum(
            1
            for row, budget in zip(rows, budgets, strict=False)
            if str(row.get("status")) == "success" and budget["model_calls"] > 0
        )
        dashboard.append(
            {
                "domain": domain,
                "sample_count": len(rows),
                "pass_count": status_counts.get("success", 0),
                "partial_count": status_counts.get("partial", 0),
                "fail_count": status_counts.get("fail", 0),
                "real_sample_pass_rate": (
                    status_counts.get("success", 0) / len(rows) if rows else 0.0
                ),
                "proof_risk_count": proof_risk_count,
                "model_calls": sum(item["model_calls"] for item in budgets),
                "tool_calls": sum(item["tool_calls"] for item in budgets),
                "tool_solved_count": tool_solved,
                "model_solved_count": model_solved,
                "model_verified_count": sum(
                    1
                    for row, budget in zip(rows, budgets, strict=False)
                    if budget["model_calls"] > 0
                    and bool((row.get("verification") or {}).get("passed"))
                ),
                "failure_question_ids": failure_ids,
                "failure_replay_links": [
                    f"failure_replay_report.md#case-{qid.lower().replace('_', '-')}"
                    for qid in failure_ids
                ],
            }
        )
    return dashboard


def _render_domain_dashboard(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Real API Sample Domain Dashboard",
        "",
        "| Domain | Samples | Pass | Partial | Fail | Proof Risks | Model Calls | Tool Calls | Tool Solved | Model Solved | Model Verified | Failures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        failures = ", ".join(str(x) for x in row.get("failure_question_ids", []))
        lines.append(
            "| {domain} | {sample_count} | {pass_count} | {partial_count} | {fail_count} | {proof_risk_count} | {model_calls} | {tool_calls} | {tool_solved_count} | {model_solved_count} | {model_verified_count} | {failures} |".format(
                failures=failures or "none",
                **row,
            )
        )
    return "\n".join(lines) + "\n"


def _is_retryable_failure(result: Any) -> bool:
    if getattr(result, "status", "") != "fail":
        return False
    text = " ".join(
        str(value or "")
        for value in [
            getattr(result, "error", ""),
            getattr(getattr(result, "verification", None), "notes", ""),
        ]
    ).casefold()
    return any(snippet in text for snippet in _RETRYABLE_ERROR_SNIPPETS)


def _solve_with_retries(
    row: dict[str, Any],
    *,
    trace_dir: Path,
    mode: str,
    enable_tools: bool,
    max_attempts: int,
) -> tuple[Any, int]:
    if not 1 <= max_attempts <= MAX_GATE_ATTEMPTS:
        raise ValueError("max_attempts is outside the safe range")
    attempts = max_attempts
    last_result: Any | None = None
    for attempt in range(1, attempts + 1):
        try:
            question = MathQuestion.model_validate(row)
            result = solve_question(
                question,
                mock=False,
                enable_tools=enable_tools,
                save_trace=True,
                trace_dir=trace_dir,
                run_mode=mode,
            )
        except Exception as exc:
            result = make_failure_result(
                question_id=str(row.get("question_id", "unknown")),
                question=str(row.get("question", "")),
                error_message=safe_exception_text(exc),
            )
        last_result = result
        if not _is_retryable_failure(result):
            return result, attempt
    return last_result, attempts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a low-cost real Intern-S1 sample gate across the official-style "
            "18-domain synthetic suite."
        )
    )
    parser.add_argument("--input", default="data/official_style_18domain_112.jsonl")
    parser.add_argument(
        "--answers", default="data/official_style_18domain_112_answers.jsonl"
    )
    parser.add_argument("--out-dir", default="outputs/real_api_sample_gate")
    parser.add_argument("--per-domain", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--rerun-failures-from",
        default=None,
        help=(
            "Rerun only question IDs listed in a previous failure replay report "
            "(.json preferred; Markdown Case headings are also supported)."
        ),
    )
    parser.add_argument("--mode", choices=["fast", "full"], default="fast")
    parser.add_argument("--enable-tools", action="store_true", default=True)
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="Retry transient real API failures up to this many attempts per item.",
    )
    parser.add_argument(
        "--include-proof",
        dest="include_proof",
        action="store_true",
        default=False,
        help=(
            "Generate proof samples and a manual-review pack. This review mode cannot "
            "produce an automatic gate PASS without external semantic decisions."
        ),
    )
    parser.add_argument(
        "--no-include-proof",
        dest="include_proof",
        action="store_false",
        help="Only sample the first --per-domain items per domain.",
    )
    parser.add_argument("--real", action="store_true", default=False)
    parser.add_argument("--allow-real", action="store_true", default=False)
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        default=False,
        help=(
            "Skip the one-call real API connectivity preflight. Use only after "
            "a trusted environment has already been verified."
        ),
    )
    parser.add_argument(
        "--allow-missing-model-call",
        action="store_true",
        default=False,
        help=(
            "Deprecated unsafe override; retained for CLI compatibility and rejected."
        ),
    )
    return parser


def main() -> int:
    load_dotenv(override=False)
    args = build_parser().parse_args()
    if not args.real or not args.allow_real:
        print(
            "real_api_sample_gate requires explicit --real --allow-real",
            file=sys.stderr,
        )
        return 2
    if args.allow_missing_model_call:
        print(
            "--allow-missing-model-call is rejected because model-call evidence is mandatory",
            file=sys.stderr,
        )
        return 2
    if not 1 <= args.per_domain <= 100:
        print("--per-domain must be between 1 and 100", file=sys.stderr)
        return 2
    if args.limit is not None and not 1 <= args.limit <= MAX_GATE_ITEMS:
        print(f"--limit must be between 1 and {MAX_GATE_ITEMS}", file=sys.stderr)
        return 2
    if not 1 <= args.max_attempts <= MAX_GATE_ATTEMPTS:
        print(
            f"--max-attempts must be between 1 and {MAX_GATE_ATTEMPTS}",
            file=sys.stderr,
        )
        return 2
    client = InternS1Client(mock=False)
    try:
        client._validate_real_mode_config()
    except ValueError as exc:
        print(safe_exception_text(exc), file=sys.stderr)
        return 2
    if not args.skip_preflight:
        preflight_ok, preflight_message = _run_real_preflight(client)
        if not preflight_ok:
            print(f"real_api_preflight_failed: {preflight_message}", file=sys.stderr)
            return 6

    out_dir = Path(args.out_dir).absolute()
    trace_dir = out_dir / "traces"
    try:
        ensure_dir(out_dir)
        ensure_dir(trace_dir)
    except OSError as exc:
        print(safe_exception_text(exc), file=sys.stderr)
        return 2
    try:
        if any(trace_dir.iterdir()):
            print(
                "trace directory must be empty for a fresh real gate run",
                file=sys.stderr,
            )
            return 2
    except OSError as exc:
        print(safe_exception_text(exc), file=sys.stderr)
        return 2

    try:
        questions = _load_jsonl(args.input)
        answers = _load_jsonl(args.answers)
    except ValueError as exc:
        print(safe_exception_text(exc), file=sys.stderr)
        return 2
    selected_ids = _select_question_ids(
        answers,
        args.per_domain,
        args.limit,
        include_proof=bool(args.include_proof),
    )
    rerun_failure_ids: set[str] = set()
    if args.rerun_failures_from:
        try:
            rerun_failure_ids = _failure_question_ids_from_report(
                args.rerun_failures_from
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(safe_exception_text(exc), file=sys.stderr)
            return 2
        if not rerun_failure_ids:
            print("--rerun-failures-from did not contain question IDs", file=sys.stderr)
            return 2
        selected_ids = set(sorted(rerun_failure_ids))
        if args.limit is not None:
            selected_ids = set(sorted(selected_ids)[: args.limit])
    selected_questions = [
        row for row in questions if row.get("question_id") in selected_ids
    ]
    if len(selected_questions) > MAX_GATE_ITEMS:
        print(
            f"selected sample exceeds the {MAX_GATE_ITEMS}-item limit", file=sys.stderr
        )
        return 2
    selected_answers = [
        row for row in answers if row.get("question_id") in selected_ids
    ]
    missing_selected_ids = selected_ids - {
        str(row.get("question_id")) for row in selected_questions
    }
    if missing_selected_ids:
        print(
            "selected question IDs not found in input: "
            + ", ".join(sorted(missing_selected_ids)[:20]),
            file=sys.stderr,
        )
        return 2
    sample_questions_path = out_dir / "sample_questions.jsonl"
    sample_answers_path = out_dir / "sample_answers.jsonl"
    results_path = out_dir / "results.jsonl"
    report_path = out_dir / "evaluation_report.md"
    failure_report_path = out_dir / "failure_replay_report.md"
    proof_review_path = out_dir / "proof_manual_review_pack.md"
    domain_dashboard_path = out_dir / "domain_dashboard.md"
    protected_inputs = [Path(args.input), Path(args.answers)]
    if args.rerun_failures_from:
        protected_inputs.append(Path(args.rerun_failures_from))
    output_paths = [
        sample_questions_path,
        sample_answers_path,
        results_path,
        report_path,
        failure_report_path,
        proof_review_path,
        domain_dashboard_path,
        domain_dashboard_path.with_suffix(".json"),
        out_dir / "real_api_sample_gate_summary.json",
    ]
    if any(path_is_within(source, out_dir) for source in protected_inputs) or any(
        paths_alias(source, output)
        for source in protected_inputs
        for output in output_paths
    ):
        print("output paths must not alias input files", file=sys.stderr)
        return 2
    _write_jsonl(sample_questions_path, selected_questions)
    _write_jsonl(sample_answers_path, selected_answers)

    started = time.perf_counter()
    attempt_counts: dict[str, int] = {}
    result_lines: list[str] = []
    total_result_chars = 0
    for row in selected_questions:
        result, attempts_used = _solve_with_retries(
            row,
            trace_dir=trace_dir,
            mode=args.mode,
            enable_tools=bool(args.enable_tools),
            max_attempts=int(args.max_attempts),
        )
        attempt_counts[str(row.get("question_id", "unknown"))] = attempts_used
        result_line = result.model_dump_json(ensure_ascii=False) + "\n"
        total_result_chars += len(result_line)
        if (
            len(result_line) > MAX_RESULT_LINE_CHARS
            or total_result_chars > MAX_RESULTS_CHARS
        ):
            print("result output exceeds the safe size limit", file=sys.stderr)
            return 2
        result_lines.append(result_line)
    atomic_text_write("".join(result_lines), results_path)

    metrics = evaluate_results(results_path, sample_answers_path, trace_dir)
    safe_text_write(
        render_markdown_report(metrics, str(results_path), str(sample_answers_path)),
        report_path,
    )
    failures = write_failure_report(
        results_path=results_path,
        answers_path=sample_answers_path,
        trace_dir=trace_dir,
        out_path=failure_report_path,
        include_format_only=True,
    )
    all_failure_rows = build_failure_rows(
        results_path=results_path,
        answers_path=sample_answers_path,
        trace_dir=trace_dir,
        include_format_only=True,
    )
    proof_rows = write_proof_review_pack(
        results_path=results_path,
        answers_path=sample_answers_path,
        trace_dir=trace_dir,
        out_path=proof_review_path,
    )
    result_rows = _load_jsonl(results_path)
    status_counts = Counter(str(row.get("status", "unknown")) for row in result_rows)
    domain_dashboard = _build_domain_dashboard(
        result_rows=result_rows,
        answer_rows=selected_answers,
        trace_dir=trace_dir,
        proof_rows=proof_rows,
        failure_rows=all_failure_rows,
    )
    safe_text_write(_render_domain_dashboard(domain_dashboard), domain_dashboard_path)
    safe_text_write(
        json.dumps(domain_dashboard, ensure_ascii=False, indent=2),
        domain_dashboard_path.with_suffix(".json"),
    )
    model_missing_ids = [
        str(row.get("question_id"))
        for row in selected_questions
        if _trace_model_call_count(trace_dir, str(row.get("question_id"))) == 0
    ]
    sample_count = len(selected_questions)
    pass_count = status_counts.get("success", 0)
    partial_count = status_counts.get("partial", 0)
    fail_count = status_counts.get("fail", 0)
    coverage = metrics.get("answer_coverage_rate", 0.0)
    rerun_mode = bool(args.rerun_failures_from)
    if rerun_mode:
        selected_answer_ids = {str(row.get("question_id")) for row in selected_answers}
        coverage_requirements_ok = bool(
            sample_count > 0
            and selected_answer_ids
            == {str(row.get("question_id")) for row in selected_questions}
        )
    else:
        coverage_requirements_ok = _sample_coverage_ok(
            selected_answers,
            per_domain=int(args.per_domain),
            include_proof=bool(args.include_proof),
        )
    trace_integrity_ok = _trace_integrity_ok(metrics, sample_count)
    automated_scope_passed = bool(
        sample_count > 0
        and len(result_rows) == sample_count
        and pass_count == sample_count
        and partial_count == 0
        and fail_count == 0
        and not failures
        and not model_missing_ids
        and not args.include_proof
        and metrics.get("evaluation_integrity_ok") is True
        and metrics.get("evaluation_pass_count") == sample_count
        and metrics.get("evaluation_pass_rate") == 1.0
        and coverage_requirements_ok
        and trace_integrity_ok
        and isinstance(coverage, (int, float))
        and not isinstance(coverage, bool)
        and float(coverage) == 1.0
    )
    gate_passed = bool(automated_scope_passed and not rerun_mode)
    rerun_passed = bool(automated_scope_passed and rerun_mode)
    summary = {
        "input": args.input,
        "answers": args.answers,
        "sample_questions": str(sample_questions_path),
        "sample_answers": str(sample_answers_path),
        "results": str(results_path),
        "evaluation_report": str(report_path),
        "failure_report": str(failure_report_path),
        "proof_manual_review_pack": str(proof_review_path),
        "domain_dashboard": str(domain_dashboard_path),
        "real": True,
        "mode": args.mode,
        "enable_tools": bool(args.enable_tools),
        "per_domain": args.per_domain,
        "include_proof": bool(args.include_proof),
        "proof_manual_review_required": bool(args.include_proof),
        "max_attempts": int(args.max_attempts),
        "preflight": "skipped" if args.skip_preflight else "passed",
        "rerun_failures_from": args.rerun_failures_from,
        "gate_scope": "failure_subset" if rerun_mode else "full_18_domain_sample",
        "rerun_passed": rerun_passed,
        "rerun_failure_ids": sorted(rerun_failure_ids),
        "retry_attempt_count": sum(
            max(0, count - 1) for count in attempt_counts.values()
        ),
        "retried_question_ids": [
            qid for qid, count in attempt_counts.items() if count > 1
        ],
        "sample_count": sample_count,
        "domain_count": len({row.get("domain") for row in selected_answers}),
        "status_counts": dict(sorted(status_counts.items())),
        "pass_count": pass_count,
        "partial_count": partial_count,
        "fail_count": fail_count,
        "pass_rate": (
            status_counts.get("success", 0) / len(selected_questions)
            if selected_questions
            else 0.0
        ),
        "failure_count": len(failures),
        "evaluation_integrity_ok": metrics.get("evaluation_integrity_ok") is True,
        "answer_coverage_rate": coverage,
        "gate_passed": gate_passed,
        "coverage_requirements_ok": coverage_requirements_ok,
        "expected_domain_count": len(EXPECTED_DOMAINS),
        "trace_integrity_ok": trace_integrity_ok,
        "format_only_failure_count": sum(
            1
            for row in all_failure_rows
            if row.get("category") == "format_only_exact_mismatch"
        ),
        "proof_review_count": len(proof_rows),
        "missing_model_call_count": len(model_missing_ids),
        "missing_model_call_ids": model_missing_ids,
        "elapsed_seconds": time.perf_counter() - started,
        "average_latency_seconds": metrics.get("average_latency_seconds", 0.0),
        "total_model_calls": metrics.get("total_model_calls", 0),
        "total_tool_calls": metrics.get("total_tool_calls", 0),
        "tool_solved_count": metrics.get("tool_solved_count", 0),
        "model_solved_count": metrics.get("model_solved_count", 0),
        "model_verified_count": metrics.get("model_verified_count", 0),
        "domain_dashboard_rows": domain_dashboard,
        "metrics": metrics,
    }
    summary_path = out_dir / "real_api_sample_gate_summary.json"
    safe_text_write(json.dumps(summary, ensure_ascii=False, indent=2), summary_path)
    print(f"summary={summary_path}")
    if model_missing_ids:
        return 5
    return 0 if gate_passed or rerun_passed else 4


if __name__ == "__main__":
    raise SystemExit(main())
