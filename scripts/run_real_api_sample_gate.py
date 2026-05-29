from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from math_agent.clients.interns1_client import InternS1Client
from math_agent.evaluation.failure_report import (
    build_failure_rows,
    write_failure_report,
)
from math_agent.evaluation.metrics import evaluate_results, render_markdown_report
from math_agent.evaluation.proof_review import write_proof_review_pack
from math_agent.pipeline import solve_question
from math_agent.schemas import MathQuestion, make_failure_result

_RETRYABLE_ERROR_SNIPPETS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection",
    "rate limit",
    "429",
    "500",
    "502",
    "503",
    "504",
)


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _trace_model_call_count(trace_dir: Path, question_id: str) -> int:
    trace_path = trace_dir / f"{question_id}.json"
    if not trace_path.exists():
        return 0
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    calls = trace.get("model_calls")
    return len(calls) if isinstance(calls, list) else 0


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
    attempts = max(1, max_attempts)
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
                error_message=str(exc),
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
        default=True,
        help="Include one proof-quality item per domain when available.",
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
        "--allow-missing-model-call",
        action="store_true",
        default=False,
        help="Do not fail when a selected item has no model call in its trace.",
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
    if args.per_domain < 1:
        print("--per-domain must be >= 1", file=sys.stderr)
        return 2
    if args.max_attempts < 1:
        print("--max-attempts must be >= 1", file=sys.stderr)
        return 2
    try:
        InternS1Client(mock=False)._validate_real_mode_config()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    trace_dir = out_dir / "traces"
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)

    questions = _load_jsonl(args.input)
    answers = _load_jsonl(args.answers)
    selected_ids = _select_question_ids(
        answers,
        args.per_domain,
        args.limit,
        include_proof=bool(args.include_proof),
    )
    selected_questions = [
        row for row in questions if row.get("question_id") in selected_ids
    ]
    selected_answers = [
        row for row in answers if row.get("question_id") in selected_ids
    ]
    sample_questions_path = out_dir / "sample_questions.jsonl"
    sample_answers_path = out_dir / "sample_answers.jsonl"
    results_path = out_dir / "results.jsonl"
    report_path = out_dir / "evaluation_report.md"
    failure_report_path = out_dir / "failure_replay_report.md"
    proof_review_path = out_dir / "proof_manual_review_pack.md"
    _write_jsonl(sample_questions_path, selected_questions)
    _write_jsonl(sample_answers_path, selected_answers)

    started = time.perf_counter()
    attempt_counts: dict[str, int] = {}
    with results_path.open("w", encoding="utf-8") as fout:
        for row in selected_questions:
            result, attempts_used = _solve_with_retries(
                row,
                trace_dir=trace_dir,
                mode=args.mode,
                enable_tools=bool(args.enable_tools),
                max_attempts=int(args.max_attempts),
            )
            attempt_counts[str(row.get("question_id", "unknown"))] = attempts_used
            fout.write(result.model_dump_json(ensure_ascii=False) + "\n")

    metrics = evaluate_results(results_path, sample_answers_path, trace_dir)
    report_path.write_text(
        render_markdown_report(metrics, str(results_path), str(sample_answers_path)),
        encoding="utf-8",
    )
    failures = write_failure_report(
        results_path=results_path,
        answers_path=sample_answers_path,
        trace_dir=trace_dir,
        out_path=failure_report_path,
        include_format_only=False,
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
    model_missing_ids = [
        str(row.get("question_id"))
        for row in selected_questions
        if _trace_model_call_count(trace_dir, str(row.get("question_id"))) == 0
    ]
    summary = {
        "input": args.input,
        "answers": args.answers,
        "sample_questions": str(sample_questions_path),
        "sample_answers": str(sample_answers_path),
        "results": str(results_path),
        "evaluation_report": str(report_path),
        "failure_report": str(failure_report_path),
        "proof_manual_review_pack": str(proof_review_path),
        "real": True,
        "mode": args.mode,
        "enable_tools": bool(args.enable_tools),
        "per_domain": args.per_domain,
        "include_proof": bool(args.include_proof),
        "max_attempts": int(args.max_attempts),
        "retry_attempt_count": sum(
            max(0, count - 1) for count in attempt_counts.values()
        ),
        "retried_question_ids": [
            qid for qid, count in attempt_counts.items() if count > 1
        ],
        "sample_count": len(selected_questions),
        "domain_count": len({row.get("domain") for row in selected_answers}),
        "failure_count": len(failures),
        "format_only_failure_count": sum(
            1
            for row in all_failure_rows
            if row.get("category") == "format_only_exact_mismatch"
        ),
        "proof_review_count": len(proof_rows),
        "missing_model_call_count": len(model_missing_ids),
        "missing_model_call_ids": model_missing_ids,
        "elapsed_seconds": time.perf_counter() - started,
        "metrics": metrics,
    }
    summary_path = out_dir / "real_api_sample_gate_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"summary={summary_path}")
    if model_missing_ids and not args.allow_missing_model_call:
        return 5
    return 0 if not failures else 4


if __name__ == "__main__":
    raise SystemExit(main())
