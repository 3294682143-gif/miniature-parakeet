from __future__ import annotations

import json
import shlex
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.pipeline import solve_question
from math_agent.schemas import MathQuestion

from .io import load_dry_run_questions, validate_dry_run_questions

FORBIDDEN_RESULTS_NAME = "official_results.jsonl"
OFFICIAL_WARNING = (
    "This is NOT official evaluation. Do not claim official accuracy and do not rename "
    "dry_run_results.jsonl to official_results.jsonl."
)


@dataclass
class DryRunConfig:
    input_path: str
    out_dir: str
    results_name: str
    mode: str
    enable_tools: bool
    mock: bool
    real: bool
    hard_mode: bool
    hard_mode_level: str
    save_trace: bool
    trace_dir: str | None
    limit: int | None
    run_id: str
    created_at: str


@dataclass
class DryRunItemResult:
    question_id: str
    status: str
    final_answer: dict[str, Any] | None
    raw_result: dict[str, Any] | None
    error: str | None
    latency_ms: int
    trace_path: str | None


@dataclass
class DryRunSummary:
    run_id: str
    total: int
    success_count: int
    fail_count: int
    invalid_count: int
    json_valid_count: int
    missing_final_count: int
    average_latency_ms: float
    results_path: str
    report_path: str
    trace_dir: str | None
    official_warning: str


def build_dry_run_config(**kwargs: Any) -> DryRunConfig:
    results_name = kwargs.get("results_name", "dry_run_results.jsonl")
    if results_name == FORBIDDEN_RESULTS_NAME:
        raise ValueError("forbidden_official_results_name")
    real = bool(kwargs.get("real", False))
    allow_real = bool(kwargs.get("allow_real", False))
    if real and not allow_real:
        raise ValueError("real_run_requires_allow_real")
    if real:
        raise ValueError("real_run_blocked_in_dry_run_harness")
    run_id = kwargs.get("run_id") or f"dryrun-{uuid.uuid4().hex[:12]}"
    created_at = kwargs.get("created_at") or datetime.now(UTC).isoformat()
    return DryRunConfig(
        input_path=str(kwargs["input_path"]),
        out_dir=str(kwargs.get("out_dir", "outputs/official_dry_run")),
        results_name=results_name,
        mode=str(kwargs.get("mode", "fast")),
        enable_tools=bool(kwargs.get("enable_tools", False)),
        mock=bool(kwargs.get("mock", True)),
        real=real,
        hard_mode=bool(kwargs.get("hard_mode", False)),
        hard_mode_level=str(kwargs.get("hard_mode_level", "standard")),
        save_trace=bool(kwargs.get("save_trace", True)),
        trace_dir=kwargs.get("trace_dir"),
        limit=kwargs.get("limit"),
        run_id=run_id,
        created_at=created_at,
    )


def run_one_question(question: Any, config: DryRunConfig) -> DryRunItemResult:
    start = time.perf_counter()
    try:
        policy = None
        if config.hard_mode:
            policy = build_hard_mode_policy(enabled=True, level=config.hard_mode_level)
        result = solve_question(
            MathQuestion(question=question.question, question_id=question.question_id),
            mock=config.mock,
            enable_tools=config.enable_tools,
            save_trace=config.save_trace,
            trace_dir=config.trace_dir or "outputs/traces",
            run_mode=config.mode,
            hard_mode_policy=policy,
        )
        raw = result.model_dump()
        final_answer = raw.get("final_answer")
        status = str(raw.get("status", "fail"))
        err = raw.get("error")
    except Exception as exc:
        raw = {"question_id": question.question_id, "error": str(exc), "status": "fail"}
        final_answer = None
        status = "fail"
        err = str(exc)
    latency_ms = int((time.perf_counter() - start) * 1000)
    return DryRunItemResult(
        question_id=question.question_id,
        status=status,
        final_answer=final_answer,
        raw_result=raw,
        error=err,
        latency_ms=latency_ms,
        trace_path=None,
    )


def dry_run_summary_to_metadata(
    summary: DryRunSummary, config: DryRunConfig
) -> dict[str, Any]:
    return {"summary": asdict(summary), "config": asdict(config)}


def write_dry_run_outputs(
    *,
    config: DryRunConfig,
    item_results: list[DryRunItemResult],
    invalid_cases: list[dict[str, Any]],
    summary: DryRunSummary,
    command: str,
) -> None:
    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if config.results_name == FORBIDDEN_RESULTS_NAME:
        raise ValueError(
            "forbidden_official_results_name: "
            "dry_run_results.jsonl must not be renamed to official_results.jsonl"
        )
    results_path = out_dir / config.results_name
    with results_path.open("w", encoding="utf-8") as f:
        for item in item_results:
            raw = item.raw_result or {}
            row = {
                "question_id": item.question_id,
                "status": item.status,
                "final_answer": item.final_answer,
                "confidence": raw.get("confidence"),
                "verification": raw.get("verification"),
                "metadata": {"run_id": config.run_id},
                "latency_ms": item.latency_ms,
                "trace_path": item.trace_path,
                "error": item.error,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out_dir / "invalid_cases.jsonl").open("w", encoding="utf-8") as f:
        for row in invalid_cases:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "dry_run_summary.json").write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run_record = {
        "run_id": config.run_id,
        "created_at": config.created_at,
        "command": command,
        "elapsed_ms": sum(i.latency_ms for i in item_results),
        "errors": [i.error for i in item_results if i.error],
        "trace_dir": config.trace_dir,
        "result_count": len(item_results),
        "invalid_count": len(invalid_cases),
    }
    (out_dir / "run_record.json").write_text(
        json.dumps(run_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "config_snapshot.json").write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_official_dry_run(config: DryRunConfig, command: str = "") -> DryRunSummary:
    if config.results_name == FORBIDDEN_RESULTS_NAME:
        raise ValueError("forbidden_official_results_name")
    questions = load_dry_run_questions(config.input_path, limit=config.limit)
    stats = validate_dry_run_questions(questions)
    invalid_cases: list[dict[str, Any]] = []
    item_results: list[DryRunItemResult] = []
    for q in questions:
        if q.metadata.get("_invalid"):
            invalid_cases.append(
                {
                    "question_id": q.question_id,
                    "error": q.metadata.get("_error", "invalid"),
                    "metadata": q.metadata,
                }
            )
            continue
        item_results.append(run_one_question(q, config))
    total_latency = sum(i.latency_ms for i in item_results)
    success_count = sum(1 for i in item_results if i.status == "success")
    fail_count = len(item_results) - success_count
    missing_final = sum(1 for i in item_results if not i.final_answer)
    out_dir = Path(config.out_dir)
    summary = DryRunSummary(
        run_id=config.run_id,
        total=len(questions),
        success_count=success_count,
        fail_count=fail_count,
        invalid_count=len(invalid_cases),
        json_valid_count=stats["valid"],
        missing_final_count=missing_final,
        average_latency_ms=(total_latency / len(item_results)) if item_results else 0.0,
        results_path=str(out_dir / config.results_name),
        report_path=str(out_dir / "dry_run_report.md"),
        trace_dir=config.trace_dir if config.save_trace else None,
        official_warning=OFFICIAL_WARNING,
    )
    write_dry_run_outputs(
        config=config,
        item_results=item_results,
        invalid_cases=invalid_cases,
        summary=summary,
        command=command,
    )
    from .report import render_dry_run_report, write_report

    write_report(
        summary.report_path, render_dry_run_report(summary, config, item_results)
    )
    return summary


def command_string(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)
