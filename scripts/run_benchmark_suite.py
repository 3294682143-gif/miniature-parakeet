from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.evaluation.failure_report import write_failure_report
from math_agent.evaluation.metrics import evaluate_results, render_markdown_report
from math_agent.evaluation.proof_review import write_proof_review_pack
from math_agent.harness.trace_reader import read_trace
from math_agent.io_utils import load_bounded_jsonl, path_is_within, paths_alias
from math_agent.logging_utils import (
    atomic_text_write,
    ensure_dir,
    safe_text_write,
    trace_path_for_question,
)
from math_agent.pipeline import solve_question
from math_agent.schemas import MathQuestion

MAX_BENCHMARK_ITEMS = 1_000
MAX_RESULT_LINE_CHARS = 1_000_000
MAX_RESULTS_CHARS = 64 * 1024 * 1024


def _load_questions(path: str | Path, limit: int | None = None) -> list[MathQuestion]:
    rows, _ = load_bounded_jsonl(path, require_objects=True)
    selected = rows if limit is None else rows[:limit]
    return [MathQuestion.model_validate(row) for row in selected]


def _read_trace_counts(trace_dir: Path, question_id: str) -> dict[str, int]:
    path = trace_path_for_question(trace_dir, question_id)
    if not path.exists():
        return {"model_calls": 0, "tool_calls": 0, "trace_found": 0}
    loaded = read_trace(path)
    if loaded.get("ok") is not True or not isinstance(loaded.get("trace"), dict):
        return {"model_calls": 0, "tool_calls": 0, "trace_found": 0}
    trace = loaded["trace"]
    model_calls = trace.get("model_calls")
    tool_calls = trace.get("tool_calls")
    return {
        "model_calls": len(model_calls) if isinstance(model_calls, list) else 0,
        "tool_calls": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "trace_found": 1,
    }


def _int_stat(stats: dict[str, object], key: str) -> int:
    value = stats.get(key, 0)
    return value if isinstance(value, int) else 0


def _float_stat(stats: dict[str, object], key: str) -> float:
    value = stats.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _write_eval_artifacts(
    results_path: Path,
    answers_path: str | None,
    trace_dir: Path,
    report_path: Path,
    failure_report_path: Path,
) -> dict:
    metrics = evaluate_results(results_path, answers_path, trace_dir)
    safe_text_write(
        render_markdown_report(metrics, str(results_path), answers_path),
        report_path,
    )
    write_failure_report(
        results_path=results_path,
        answers_path=answers_path,
        trace_dir=trace_dir,
        out_path=failure_report_path,
    )
    return metrics


def _run_label(
    questions: list[MathQuestion],
    out_dir: Path,
    label: str,
    mode_for_index: Callable[[int], str],
    real: bool,
    enable_tools: bool,
    answers_path: str | None,
    hard_mode_level: str = "off",
) -> dict:
    label_dir = out_dir / label
    trace_dir = label_dir / "traces"
    ensure_dir(label_dir)
    ensure_dir(trace_dir)
    results_path = label_dir / "results.jsonl"
    report_path = label_dir / "evaluation_report.md"
    failure_report_path = label_dir / "failure_replay_report.md"
    proof_review_path = label_dir / "proof_manual_review_pack.md"
    stats_path = label_dir / "run_stats.json"

    hard_policy = (
        build_hard_mode_policy(enabled=True, level=hard_mode_level)
        if hard_mode_level != "off"
        else None
    )
    stats: dict[str, object] = {
        "label": label,
        "real": real,
        "enable_tools": enable_tools,
        "hard_mode_level": hard_mode_level,
        "question_count": len(questions),
        "status_counts": {},
        "mode_counts": {},
        "total_elapsed_seconds": 0.0,
        "average_elapsed_seconds": 0.0,
        "total_model_calls": 0,
        "total_tool_calls": 0,
        "trace_found_count": 0,
    }
    status_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    started = time.perf_counter()
    result_lines: list[str] = []
    total_result_chars = 0
    for idx, question in enumerate(questions):
        run_mode = mode_for_index(idx)
        item_started = time.perf_counter()
        result = solve_question(
            question,
            mock=not real,
            enable_tools=enable_tools,
            save_trace=True,
            trace_dir=trace_dir,
            run_mode=run_mode,
            hard_mode_policy=hard_policy,
        )
        elapsed = time.perf_counter() - item_started
        result_line = result.model_dump_json(ensure_ascii=False) + "\n"
        total_result_chars += len(result_line)
        if (
            len(result_line) > MAX_RESULT_LINE_CHARS
            or total_result_chars > MAX_RESULTS_CHARS
        ):
            raise ValueError("result output exceeds the safe size limit")
        result_lines.append(result_line)
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        mode_counts[run_mode] = mode_counts.get(run_mode, 0) + 1
        stats["total_elapsed_seconds"] = (
            _float_stat(stats, "total_elapsed_seconds") + elapsed
        )
        counts = _read_trace_counts(trace_dir, result.question_id)
        stats["total_model_calls"] = (
            _int_stat(stats, "total_model_calls") + counts["model_calls"]
        )
        stats["total_tool_calls"] = (
            _int_stat(stats, "total_tool_calls") + counts["tool_calls"]
        )
        stats["trace_found_count"] = (
            _int_stat(stats, "trace_found_count") + counts["trace_found"]
        )
    atomic_text_write("".join(result_lines), results_path)

    stats["wall_elapsed_seconds"] = time.perf_counter() - started
    stats["average_elapsed_seconds"] = (
        _float_stat(stats, "total_elapsed_seconds") / len(questions)
        if questions
        else 0.0
    )
    stats["average_model_calls_per_item"] = (
        _int_stat(stats, "total_model_calls") / len(questions) if questions else 0.0
    )
    stats["status_counts"] = dict(sorted(status_counts.items()))
    stats["mode_counts"] = dict(sorted(mode_counts.items()))
    metrics = _write_eval_artifacts(
        results_path, answers_path, trace_dir, report_path, failure_report_path
    )
    proof_review_rows = write_proof_review_pack(
        results_path=results_path,
        answers_path=answers_path,
        trace_dir=trace_dir,
        out_path=proof_review_path,
    )
    stats["metrics"] = metrics
    stats["proof_review_count"] = len(proof_review_rows)
    stats["proof_manual_review_recommended_count"] = sum(
        1 for row in proof_review_rows if row.get("manual_review_recommended")
    )
    stats["proof_manual_review_pack"] = str(proof_review_path)
    safe_text_write(json.dumps(stats, ensure_ascii=False, indent=2), stats_path)
    return stats


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main() -> int:
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(
        description="Run official-like mixed-mode and optional hard-mode A/B benchmark suites."
    )
    parser.add_argument("--input", required=True, help="Questions JSONL")
    parser.add_argument("--answers", default=None, help="Optional answers JSONL")
    parser.add_argument("--out-dir", default="outputs/benchmark_suite")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--real", action="store_true", default=False)
    parser.add_argument("--enable-tools", action="store_true", default=False)
    parser.add_argument(
        "--mode-pattern",
        default="fast,fast,full",
        help="Comma pattern used by the mixed official-like run.",
    )
    parser.add_argument("--ab-limit", type=int, default=0)
    parser.add_argument("--ab-modes", default="fast,full")
    parser.add_argument("--hard-mode-levels", default="off,strict")
    args = parser.parse_args()

    if (
        not 1 <= args.limit <= MAX_BENCHMARK_ITEMS
        or not 0 <= args.ab_limit <= MAX_BENCHMARK_ITEMS
    ):
        parser.error(
            f"--limit must be 1..{MAX_BENCHMARK_ITEMS} and "
            f"--ab-limit must be 0..{MAX_BENCHMARK_ITEMS}"
        )
    out_dir = Path(args.out_dir).absolute()
    ensure_dir(out_dir)
    protected_inputs = [Path(args.input)]
    if args.answers:
        protected_inputs.append(Path(args.answers))
    planned_outputs = [
        out_dir / "benchmark_summary.json",
        out_dir / "mixed_official_like" / "results.jsonl",
    ]
    if any(path_is_within(source, out_dir) for source in protected_inputs) or any(
        paths_alias(source, output)
        for source in protected_inputs
        for output in planned_outputs
    ):
        parser.error("output paths must not alias input files")
    questions = _load_questions(args.input, args.limit)
    pattern = _parse_csv(args.mode_pattern) or ["fast"]
    runs: dict[str, Any] = {}
    summary: dict[str, Any] = {
        "input": args.input,
        "answers": args.answers,
        "limit": args.limit,
        "real": bool(args.real),
        "enable_tools": bool(args.enable_tools),
        "runs": runs,
    }
    runs["mixed"] = _run_label(
        questions,
        out_dir,
        "mixed_official_like",
        lambda idx: pattern[idx % len(pattern)],
        real=args.real,
        enable_tools=args.enable_tools,
        answers_path=args.answers,
    )

    if args.ab_limit > 0:
        ab_questions = questions[: args.ab_limit]
        for mode in _parse_csv(args.ab_modes):
            for level in _parse_csv(args.hard_mode_levels):
                label = f"ab_{mode}_{level}"
                runs[label] = _run_label(
                    ab_questions,
                    out_dir,
                    label,
                    lambda _idx, selected_mode=mode: selected_mode,
                    real=args.real,
                    enable_tools=args.enable_tools,
                    answers_path=args.answers,
                    hard_mode_level=level,
                )

    summary_path = out_dir / "benchmark_summary.json"
    safe_text_write(json.dumps(summary, ensure_ascii=False, indent=2), summary_path)
    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
