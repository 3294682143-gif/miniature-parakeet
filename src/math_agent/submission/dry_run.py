from __future__ import annotations

import json
import re
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.harness.trace_reader import read_trusted_program_trace
from math_agent.io_utils import path_is_within, paths_alias
from math_agent.logging_utils import (
    atomic_text_write,
    ensure_dir,
    safe_text_write,
    sanitize_trusted_trace_payload,
    trace_path_for_question,
    write_trusted_structured_artifact,
)
from math_agent.pipeline import execution_fingerprint_for_question, solve_question
from math_agent.schemas import (
    MathQuestion,
    SolveResult,
    is_valid_trace_audit_evidence,
    question_fingerprint,
)
from math_agent.security import redact_sensitive_data, safe_exception_text

from .io import DryRunQuestion, load_dry_run_questions, validate_dry_run_questions

FORBIDDEN_RESULTS_NAME = "official_results.jsonl"
_SAFE_RESULTS_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_DRY_RUN_MODES = {"fast", "full"}
_HARD_MODE_LEVELS = {"off", "light", "standard", "strict"}
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
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
    input_manifest_sha256: str = ""


@dataclass
class DryRunItemResult:
    question_id: str
    status: str
    final_answer: dict[str, Any] | None
    raw_result: dict[str, Any] | None
    error: str | None
    latency_ms: int
    trace_path: str | None
    input_fingerprint: str
    execution_fingerprint: str


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
    input_manifest_sha256: str
    official_warning: str


def _raw_result_is_success(raw: dict[str, Any]) -> bool:
    final_answer = raw.get("final_answer")
    verification = raw.get("verification")
    return (
        raw.get("status") == "success"
        and isinstance(final_answer, dict)
        and isinstance(final_answer.get("value"), str)
        and bool(final_answer["value"].strip())
        and isinstance(verification, dict)
        and verification.get("passed") is True
        and raw.get("error") is None
    )


def _strict_solve_result_payload(result: Any) -> dict[str, Any]:
    """Return a complete, type-preserving canonical SolveResult payload."""

    try:
        supplied = result.model_dump()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("dry_run_result_must_be_an_object") from exc
    if not isinstance(supplied, dict):
        raise ValueError("dry_run_result_must_be_an_object")
    try:
        validated = SolveResult.model_validate(supplied, strict=True)
        canonical = validated.model_dump()
        supplied_json = json.dumps(
            supplied,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        canonical_json = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except Exception as exc:
        raise ValueError("invalid_dry_run_result_schema") from exc
    if supplied_json != canonical_json:
        raise ValueError("noncanonical_dry_run_result_schema")
    return canonical


def _validate_results_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_dry_run_results_name")
    name = value.strip()
    stem = name.rstrip(" .").casefold().split(".", 1)[0]
    if (
        not name
        or name != value
        or "/" in name
        or "\\" in name
        or Path(name).name != name
        or name.casefold() == FORBIDDEN_RESULTS_NAME.casefold()
        or Path(name).suffix.casefold() != ".jsonl"
        or name.endswith((".", " "))
        or stem in _WINDOWS_RESERVED_NAMES
        or len(name) > 128
        or _SAFE_RESULTS_NAME.fullmatch(name) is None
    ):
        raise ValueError("forbidden_official_results_name")
    return name


def _validate_path_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"dry_run_{field_name}_must_be_a_string")
    if not value or value != value.strip() or "\x00" in value or len(value) > 32_768:
        raise ValueError(f"invalid_dry_run_{field_name}")
    try:
        Path(value)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid_dry_run_{field_name}") from exc
    return value


def _coerce_path_text(value: Any, field_name: str) -> str:
    if isinstance(value, Path):
        value = str(value)
    return _validate_path_text(value, field_name)


def _validate_run_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("dry_run_run_id_must_be_a_string")
    stem = value.rstrip(" .").casefold().split(".", 1)[0]
    if (
        not value
        or value != value.strip()
        or Path(value).name != value
        or value.endswith((".", " "))
        or stem in _WINDOWS_RESERVED_NAMES
        or _SAFE_RUN_ID.fullmatch(value) is None
    ):
        raise ValueError("invalid_dry_run_run_id")
    return value


def _validate_created_at(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("invalid_dry_run_created_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_dry_run_created_at") from exc
    if parsed.tzinfo is None:
        raise ValueError("invalid_dry_run_created_at")
    return value


def _validated_config(config: DryRunConfig) -> DryRunConfig:
    """Strictly revalidate the public dataclass at every execution boundary."""

    if not isinstance(config, DryRunConfig):
        raise ValueError("invalid_dry_run_config")
    for name in ("enable_tools", "mock", "real", "hard_mode", "save_trace"):
        if type(getattr(config, name)) is not bool:
            raise ValueError(f"dry_run_{name}_must_be_boolean")
    if config.mock is not True:
        raise ValueError("dry_run_requires_mock_mode")
    if config.real is not False:
        raise ValueError("real_run_blocked_in_dry_run_harness")
    if not isinstance(config.mode, str) or config.mode not in _DRY_RUN_MODES:
        raise ValueError("invalid_dry_run_mode")
    if (
        not isinstance(config.hard_mode_level, str)
        or config.hard_mode_level not in _HARD_MODE_LEVELS
    ):
        raise ValueError("invalid_dry_run_hard_mode_level")
    if config.limit is not None and (
        isinstance(config.limit, bool)
        or not isinstance(config.limit, int)
        or not 1 <= config.limit <= 100_000
    ):
        raise ValueError("dry_run_limit_outside_safe_range")
    input_path = _validate_path_text(config.input_path, "input_path")
    out_dir = _validate_path_text(config.out_dir, "out_dir")
    trace_dir = config.trace_dir
    if trace_dir is not None:
        trace_dir = _validate_path_text(trace_dir, "trace_dir")
    manifest = config.input_manifest_sha256
    if not isinstance(manifest, str) or (
        manifest and _SHA256_HEX.fullmatch(manifest) is None
    ):
        raise ValueError("invalid_dry_run_input_manifest_sha256")
    return replace(
        config,
        input_path=input_path,
        out_dir=out_dir,
        results_name=_validate_results_name(config.results_name),
        trace_dir=trace_dir,
        run_id=_validate_run_id(config.run_id),
        created_at=_validate_created_at(config.created_at),
        input_manifest_sha256=manifest,
    )


def build_dry_run_config(**kwargs: Any) -> DryRunConfig:
    results_name = _validate_results_name(
        kwargs.get("results_name", "dry_run_results.jsonl")
    )
    boolean_defaults = {
        "real": False,
        "allow_real": False,
        "mock": True,
        "enable_tools": False,
        "hard_mode": False,
        "save_trace": True,
    }
    flags: dict[str, bool] = {}
    for name, default in boolean_defaults.items():
        value = kwargs.get(name, default)
        if type(value) is not bool:
            raise ValueError(f"dry_run_{name}_must_be_boolean")
        flags[name] = value
    real = flags["real"]
    allow_real = flags["allow_real"]
    if real and not allow_real:
        raise ValueError("real_run_requires_allow_real")
    if real:
        raise ValueError("real_run_blocked_in_dry_run_harness")
    if not flags["mock"]:
        raise ValueError("dry_run_requires_mock_mode")
    limit = kwargs.get("limit")
    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 100_000
    ):
        raise ValueError("dry_run_limit_outside_safe_range")
    if "input_path" not in kwargs:
        raise ValueError("dry_run_input_path_is_required")
    run_id = kwargs.get("run_id")
    if run_id is None:
        run_id = f"dryrun-{uuid.uuid4().hex[:12]}"
    created_at = kwargs.get("created_at")
    if created_at is None:
        created_at = datetime.now(UTC).isoformat()
    trace_dir_value = kwargs.get("trace_dir")
    trace_dir = (
        None
        if trace_dir_value is None
        else _coerce_path_text(trace_dir_value, "trace_dir")
    )
    return _validated_config(
        DryRunConfig(
            input_path=_coerce_path_text(kwargs["input_path"], "input_path"),
            out_dir=_coerce_path_text(
                kwargs.get("out_dir", "outputs/official_dry_run"), "out_dir"
            ),
            results_name=results_name,
            mode=kwargs.get("mode", "fast"),
            enable_tools=flags["enable_tools"],
            mock=flags["mock"],
            real=real,
            hard_mode=flags["hard_mode"],
            hard_mode_level=kwargs.get("hard_mode_level", "standard"),
            save_trace=flags["save_trace"],
            trace_dir=trace_dir,
            limit=limit,
            run_id=run_id,
            created_at=created_at,
        )
    )


def _input_manifest_sha256(questions: list[DryRunQuestion]) -> str:
    records = []
    for index, question in enumerate(questions, start=1):
        records.append(
            {
                "index": index,
                "question_id": question.question_id,
                "question": question.question,
                "input_fingerprint": question_fingerprint(question.question),
                "domain": question.domain,
                "problem_type": question.problem_type,
                "answer_type": question.answer_type,
                "difficulty": question.difficulty,
                "metadata": question.metadata,
            }
        )
    canonical = json.dumps(
        {"version": "dry-run-input-manifest-v1", "records": records},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8", errors="strict")).hexdigest()


def _trace_matches_result(
    trace: dict[str, Any],
    *,
    question: MathQuestion,
    raw_result: dict[str, Any],
    input_fingerprint: str,
    execution_fingerprint: str,
) -> bool:
    final_result = trace.get("final_result")
    try:
        trace_result = SolveResult.model_validate(final_result, strict=True)
    except Exception:
        return False
    return bool(
        trace.get("question_id") == redact_sensitive_data(question.question_id)
        and trace.get("question") == redact_sensitive_data(question.question)
        and trace.get("input_fingerprint") == input_fingerprint
        and trace.get("execution_fingerprint") == execution_fingerprint
        and trace.get("final_result") == sanitize_trusted_trace_payload(raw_result)
        and is_valid_trace_audit_evidence(
            trace,
            trace_result,
            expected_real_mode=False,
        )
    )


def run_one_question(question: Any, config: DryRunConfig) -> DryRunItemResult:
    config = _validated_config(config)
    if config.save_trace and (
        config.trace_dir is None or Path(config.trace_dir).name != config.run_id
    ):
        raise ValueError("dry_run_requires_isolated_run_trace_directory")
    start = time.perf_counter()
    trace_path: str | None = None
    question_id = str(getattr(question, "question_id", "unknown"))
    input_fingerprint = ""
    execution_fingerprint = ""
    try:
        validated_question = MathQuestion(
            question=getattr(question, "question", ""),
            question_id=question_id,
        )
        question_id = validated_question.question_id
        input_fingerprint = question_fingerprint(validated_question.question)
        policy = None
        if config.hard_mode:
            policy = build_hard_mode_policy(enabled=True, level=config.hard_mode_level)
        expected_execution_fingerprint = execution_fingerprint_for_question(
            validated_question,
            mock=config.mock,
            enable_tools=config.enable_tools,
            save_trace=config.save_trace,
            trace_dir=config.trace_dir or "",
            run_mode=config.mode,
            hard_mode_policy=policy,
        )
        result = solve_question(
            validated_question,
            mock=config.mock,
            enable_tools=config.enable_tools,
            save_trace=config.save_trace,
            trace_dir=config.trace_dir or "",
            run_mode=config.mode,
            hard_mode_policy=policy,
        )
        raw_payload = _strict_solve_result_payload(result)
        raw = dict(raw_payload)
        raw_execution_fingerprint = raw.get("execution_fingerprint", "")
        if not isinstance(raw_execution_fingerprint, str) or (
            raw_execution_fingerprint
            and _SHA256_HEX.fullmatch(raw_execution_fingerprint) is None
        ):
            raise ValueError("invalid_result_execution_fingerprint")
        execution_fingerprint = raw_execution_fingerprint
        final_answer = raw.get("final_answer")
        status = str(raw.get("status", "fail"))
        err = raw.get("error")
        result_binding_is_valid = (
            raw.get("question_id") == question_id
            and raw.get("input_fingerprint") == input_fingerprint
            and bool(execution_fingerprint)
            and execution_fingerprint == expected_execution_fingerprint
            and status in {"success", "partial", "fail"}
            and (err is None or isinstance(err, str))
        )
        result_contract_is_valid = not (
            status == "success" and not _raw_result_is_success(raw)
        )
        if not result_binding_is_valid:
            status = "fail"
            err = "result_input_binding_missing_or_invalid"
            raw = {**raw, "status": "fail", "error": err}
        elif not result_contract_is_valid:
            status = "fail"
            err = "inconsistent_success_result"
            raw = {**raw, "status": "fail", "error": err}
        if config.save_trace:
            expected_trace = trace_path_for_question(
                config.trace_dir or "", question_id
            )
            trace_read = read_trusted_program_trace(expected_trace)
            trace = trace_read.get("trace")
            if (
                not result_binding_is_valid
                or not result_contract_is_valid
                or trace_read.get("ok") is not True
                or not isinstance(trace, dict)
                or not _trace_matches_result(
                    trace,
                    question=validated_question,
                    raw_result=raw_payload,
                    input_fingerprint=input_fingerprint,
                    execution_fingerprint=execution_fingerprint,
                )
            ):
                status = "fail"
                err = "trace_evidence_missing_or_invalid"
                raw = {**raw, "status": "fail", "error": err}
            else:
                trace_path = str(expected_trace.absolute())
    except Exception as exc:
        safe_error = safe_exception_text(exc)
        raw = {
            "question_id": question_id,
            "error": safe_error,
            "status": "fail",
            "input_fingerprint": input_fingerprint,
            "execution_fingerprint": execution_fingerprint,
        }
        final_answer = None
        status = "fail"
        err = safe_error
    latency_ms = int((time.perf_counter() - start) * 1000)
    return DryRunItemResult(
        question_id=question_id,
        status=status,
        final_answer=final_answer,
        raw_result=raw,
        error=err,
        latency_ms=latency_ms,
        trace_path=trace_path,
        input_fingerprint=input_fingerprint,
        execution_fingerprint=execution_fingerprint,
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
    config = _validated_config(config)
    if not config.input_manifest_sha256:
        raise ValueError("dry_run_input_manifest_is_required")
    results_name = config.results_name
    out_dir = ensure_dir(config.out_dir)
    results_path = out_dir / results_name
    result_rows = []
    for item in item_results:
        raw = item.raw_result or {}
        result_rows.append(
            {
                "question_id": item.question_id,
                "status": item.status,
                "final_answer": item.final_answer,
                "confidence": raw.get("confidence"),
                "verification": raw.get("verification"),
                "input_fingerprint": item.input_fingerprint,
                "execution_fingerprint": item.execution_fingerprint,
                "metadata": {
                    "run_id": config.run_id,
                    "input_manifest_sha256": config.input_manifest_sha256,
                },
                "latency_ms": item.latency_ms,
                "trace_path": item.trace_path,
                "error": item.error,
            }
        )
    atomic_text_write(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in result_rows),
        results_path,
    )
    safe_text_write(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in invalid_cases),
        out_dir / "invalid_cases.jsonl",
    )
    write_trusted_structured_artifact(asdict(summary), out_dir / "dry_run_summary.json")
    run_record = {
        "run_id": config.run_id,
        "created_at": config.created_at,
        "command": command,
        "elapsed_ms": sum(i.latency_ms for i in item_results),
        "errors": [i.error for i in item_results if i.error],
        "trace_dir": config.trace_dir,
        "input_manifest_sha256": config.input_manifest_sha256,
        "result_count": len(item_results),
        "invalid_count": len(invalid_cases),
    }
    write_trusted_structured_artifact(run_record, out_dir / "run_record.json")
    write_trusted_structured_artifact(asdict(config), out_dir / "config_snapshot.json")


def run_official_dry_run(config: DryRunConfig, command: str = "") -> DryRunSummary:
    config = _validated_config(config)
    results_name = config.results_name
    input_path = Path(config.input_path).absolute()
    out_dir = Path(config.out_dir).absolute()
    ensure_dir(out_dir)
    if path_is_within(input_path, out_dir) or paths_alias(
        input_path, out_dir / results_name
    ):
        raise ValueError("dry_run_input_must_be_outside_output_directory")
    effective_trace_dir: Path | None = None
    if config.save_trace:
        trace_base = (
            Path(config.trace_dir).absolute()
            if config.trace_dir is not None
            else out_dir / "traces"
        )
        if path_is_within(input_path, trace_base):
            raise ValueError("dry_run_input_must_be_outside_trace_directory")
        canonical_nested_trace = out_dir / "traces"
        if (
            paths_alias(trace_base, out_dir)
            or path_is_within(out_dir, trace_base)
            or (
                path_is_within(trace_base, out_dir)
                and not paths_alias(trace_base, canonical_nested_trace)
            )
        ):
            raise ValueError("dry_run_trace_directory_overlaps_output_artifacts")
        trace_base = ensure_dir(trace_base)
        effective_trace_dir = trace_base / config.run_id
        try:
            effective_trace_dir.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise ValueError(
                "dry_run_trace_directory_already_exists_and_cannot_be_reused"
            ) from exc
        ensure_dir(effective_trace_dir)

    questions = load_dry_run_questions(input_path, limit=config.limit)
    manifest_sha256 = _input_manifest_sha256(questions)
    execution_config = _validated_config(
        replace(
            config,
            input_path=str(input_path),
            out_dir=str(out_dir),
            trace_dir=(
                str(effective_trace_dir) if effective_trace_dir is not None else None
            ),
            input_manifest_sha256=manifest_sha256,
        )
    )
    stats = validate_dry_run_questions(questions)
    invalid_cases: list[dict[str, Any]] = []
    item_results: list[DryRunItemResult] = []
    for q in questions:
        if q.metadata.get("_invalid"):
            invalid_cases.append(
                {
                    "question_id": q.question_id,
                    "input_fingerprint": question_fingerprint(q.question),
                    "error": q.metadata.get("_error", "invalid"),
                    "metadata": q.metadata,
                }
            )
            continue
        item_results.append(run_one_question(q, execution_config))
    final_questions = load_dry_run_questions(input_path, limit=config.limit)
    if _input_manifest_sha256(final_questions) != manifest_sha256:
        raise ValueError("dry_run_input_changed_during_execution")
    total_latency = sum(i.latency_ms for i in item_results)
    success_count = sum(
        1
        for item in item_results
        if item.status == "success"
        and isinstance(item.raw_result, dict)
        and _raw_result_is_success(item.raw_result)
    )
    fail_count = len(item_results) - success_count
    missing_final = sum(
        1
        for item in item_results
        if not isinstance(item.final_answer, dict)
        or not str(
            item.final_answer.get("value") or item.final_answer.get("boxed") or ""
        ).strip()
    )
    summary = DryRunSummary(
        run_id=execution_config.run_id,
        total=len(questions),
        success_count=success_count,
        fail_count=fail_count,
        invalid_count=len(invalid_cases),
        json_valid_count=stats["valid"],
        missing_final_count=missing_final,
        average_latency_ms=(total_latency / len(item_results)) if item_results else 0.0,
        results_path=str(out_dir / results_name),
        report_path=str(out_dir / "dry_run_report.md"),
        trace_dir=(
            str(effective_trace_dir) if effective_trace_dir is not None else None
        ),
        input_manifest_sha256=manifest_sha256,
        official_warning=OFFICIAL_WARNING,
    )
    write_dry_run_outputs(
        config=execution_config,
        item_results=item_results,
        invalid_cases=invalid_cases,
        summary=summary,
        command=command,
    )
    from .report import render_dry_run_report, write_report

    write_report(
        summary.report_path,
        render_dry_run_report(summary, execution_config, item_results),
    )
    return summary


def command_string(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)
