from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from math_agent.evaluation.judge import exact_match as judge_exact_match
from math_agent.evaluation.judge import (
    is_canonical_final_answer,
    normalized_match,
    numeric_match,
    symbolic_match,
)
from math_agent.harness.trace_reader import read_trace_dir
from math_agent.io_utils import load_bounded_jsonl
from math_agent.proof import ProofRubricScore, score_proof_candidate
from math_agent.schemas import (
    SolveResult,
    is_semantically_successful,
    is_valid_trace_audit_evidence,
)
from math_agent.tools.answer_normalizer import normalize_answer as normalize_answer_core


def accuracy(correct: int, total: int) -> float:
    return correct / total if total else 0.0


def _safe_rate(n: int, d: int) -> float:
    return n / d if d else 0.0


def load_jsonl(path: str | Path) -> tuple[list[Any], int]:
    p = Path(path)
    if not p.exists():
        return [], 0
    return load_bounded_jsonl(p, tolerate_invalid=True)


@dataclass(frozen=True)
class _AnswerDataset:
    answers: dict[str, str]
    records: dict[str, dict[str, Any]]
    duplicate_ids: frozenset[str]
    json_invalid_count: int
    schema_invalid_count: int
    invalid_id_count: int
    duplicate_row_count: int
    source_exists: bool
    source_nonempty: bool

    @property
    def integrity_ok(self) -> bool:
        return not (
            self.json_invalid_count
            or self.schema_invalid_count
            or self.invalid_id_count
            or self.duplicate_ids
            or not self.source_exists
            or not self.source_nonempty
            or not self.records
        )


def _stable_answer_record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        rows,
        key=lambda row: json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )


def _load_answer_dataset(path: str | Path | None) -> _AnswerDataset:
    if not path:
        return _AnswerDataset({}, {}, frozenset(), 0, 0, 0, 0, False, False)
    source = Path(path)
    try:
        source_exists = (
            source.is_file()
            and not source.is_symlink()
            and not getattr(source, "is_junction", lambda: False)()
        )
        source_nonempty = source_exists and source.stat().st_size > 0
    except OSError:
        source_exists = False
        source_nonempty = False
    rows, json_invalid = load_jsonl(path) if source_exists else ([], 0)
    grouped: dict[str, list[dict[str, Any]]] = {}
    schema_invalid = 0
    invalid_id = 0
    for row in rows:
        if not isinstance(row, dict):
            schema_invalid += 1
            continue
        raw_qid = row.get("question_id")
        if not isinstance(raw_qid, str) or not raw_qid.strip():
            invalid_id += 1
            continue
        answer = row.get("answer")
        evaluation_mode = row.get("evaluation_mode", "short_answer")
        answer_is_scalar = isinstance(
            answer, (str, int, float, bool)
        ) and not isinstance(answer, type(None))
        if isinstance(answer, float) and not math.isfinite(answer):
            answer_is_scalar = False
        if (
            "answer" not in row
            or not answer_is_scalar
            or not str(answer).strip()
            or not isinstance(evaluation_mode, str)
            or evaluation_mode
            not in {"short_answer", "proof_validity", "proof_quality"}
        ):
            schema_invalid += 1
            continue
        grouped.setdefault(raw_qid.strip(), []).append(row)

    records = {
        qid: _stable_answer_record(answer_rows) for qid, answer_rows in grouped.items()
    }
    answers = {qid: str(row.get("answer", "")) for qid, row in records.items()}
    duplicate_ids = frozenset(
        qid for qid, answer_rows in grouped.items() if len(answer_rows) > 1
    )
    duplicate_rows = sum(
        max(0, len(answer_rows) - 1) for answer_rows in grouped.values()
    )
    return _AnswerDataset(
        answers,
        records,
        duplicate_ids,
        json_invalid,
        schema_invalid,
        invalid_id,
        duplicate_rows,
        source_exists,
        source_nonempty,
    )


def load_answers(path: str | Path | None) -> dict[str, str]:
    return _load_answer_dataset(path).answers


def load_answer_records(path: str | Path | None) -> dict[str, dict[str, Any]]:
    return _load_answer_dataset(path).records


def _match_bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "short_answer_count": 0,
        "exact_match_count": 0,
        "normalized_match_count": 0,
        "numeric_match_count": 0,
        "symbolic_match_count": 0,
        "proof_validity_count": 0,
        "proof_validity_pass_count": 0,
        "proof_quality_score_sum": 0.0,
        "proof_complete_count": 0,
        "proof_partial_count": 0,
        "proof_invalid_count": 0,
        "evaluation_pass_count": 0,
    }


def _finalize_match_buckets(
    buckets: dict[str, dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for key, bucket in sorted(buckets.items()):
        total = int(bucket["total"])
        proof_count = int(bucket["proof_validity_count"])
        out[key] = {
            **bucket,
            "exact_match_rate": _safe_rate(
                bucket["exact_match_count"], bucket["short_answer_count"]
            ),
            "normalized_match_rate": _safe_rate(
                bucket["normalized_match_count"], bucket["short_answer_count"]
            ),
            "numeric_match_rate": _safe_rate(
                bucket["numeric_match_count"], bucket["short_answer_count"]
            ),
            "symbolic_match_rate": _safe_rate(
                bucket["symbolic_match_count"], bucket["short_answer_count"]
            ),
            "proof_validity_rate": _safe_rate(
                bucket["proof_validity_pass_count"], bucket["proof_validity_count"]
            ),
            "proof_quality_average": (
                float(bucket["proof_quality_score_sum"]) / proof_count
                if proof_count
                else 0.0
            ),
            "proof_complete_rate": _safe_rate(
                bucket["proof_complete_count"], proof_count
            ),
            "evaluation_pass_rate": _safe_rate(bucket["evaluation_pass_count"], total),
        }
    return out


def _is_proof_eval_mode(eval_mode: str) -> bool:
    return eval_mode in {"proof_validity", "proof_quality"}


_EXPLANATION_TEMPLATE_VALUES = {"", "h", "n", "ok", "none", "no hint"}
_EXPLANATION_TEMPLATE_MARKERS = (
    "[mock]",
    "stable response",
    "placeholder",
    "template",
    "todo",
)
_KEY_IDEA_MARKERS = (
    "because",
    "since",
    "therefore",
    "hence",
    "formula",
    "theorem",
    "definition",
    "derivative",
    "integral",
    "limit",
    "modulo",
    "probability",
    "area",
    "matrix",
    "compact",
    "analytic",
    "proof",
    "verify",
    "substitute",
    "simplify",
    "因",
    "所以",
    "因此",
    "公式",
    "定理",
    "定义",
)


def explanation_quality_for_result(result: SolveResult) -> dict[str, object]:
    steps = [
        str(step).strip() for step in result.visible_solution_steps if str(step).strip()
    ]
    hint = (result.didactic_hint or "").strip()
    hint_norm = hint.lower()
    combined = " ".join([*steps, hint]).lower()
    template_risk = hint_norm in _EXPLANATION_TEMPLATE_VALUES or any(
        marker in combined for marker in _EXPLANATION_TEMPLATE_MARKERS
    )
    key_idea_present = any(marker in combined for marker in _KEY_IDEA_MARKERS) or any(
        token in combined
        for token in [
            str(result.problem_type).lower(),
            str(result.domain).lower(),
        ]
        if token and token != "unknown"
    )
    return {
        "visible_steps_nonempty": bool(steps),
        "visible_step_count": len(steps),
        "didactic_hint_nonempty": bool(hint),
        "didactic_hint_template_risk": template_risk,
        "key_idea_present": key_idea_present,
    }


def _explanation_quality_metrics(results: list[SolveResult]) -> dict[str, object]:
    checked = len(results)
    qualities = [explanation_quality_for_result(result) for result in results]
    visible = sum(int(bool(q["visible_steps_nonempty"])) for q in qualities)
    hints = sum(int(bool(q["didactic_hint_nonempty"])) for q in qualities)
    template_risk = sum(int(bool(q["didactic_hint_template_risk"])) for q in qualities)
    key_idea = sum(int(bool(q["key_idea_present"])) for q in qualities)
    total_steps = sum(
        q["visible_step_count"] if isinstance(q["visible_step_count"], int) else 0
        for q in qualities
    )
    return {
        "explanation_checked_count": checked,
        "visible_steps_nonempty_count": visible,
        "visible_steps_nonempty_rate": _safe_rate(visible, checked),
        "average_visible_step_count": _safe_rate(total_steps, checked),
        "didactic_hint_nonempty_count": hints,
        "didactic_hint_nonempty_rate": _safe_rate(hints, checked),
        "didactic_hint_template_risk_count": template_risk,
        "didactic_hint_template_risk_rate": _safe_rate(template_risk, checked),
        "key_idea_coverage_count": key_idea,
        "key_idea_coverage_rate": _safe_rate(key_idea, checked),
    }


def _proof_text_for_result(result: SolveResult) -> str:
    steps = "\n".join(str(step) for step in result.visible_solution_steps)
    final_value = result.final_answer.value.strip()
    if steps.strip() and final_value:
        return f"{steps}\n{final_value}"
    return steps.strip() or final_value


def proof_quality_score(result: SolveResult) -> ProofRubricScore:
    return score_proof_candidate(
        {
            "candidate_id": result.question_id,
            "proof_text": _proof_text_for_result(result),
        },
        answer_type="proof",
        candidate_id=result.question_id,
    )


def _proof_min_score(answer_row: dict[str, Any] | None, eval_mode: str) -> float:
    default = 0.68 if eval_mode == "proof_quality" else 0.35
    if not answer_row:
        return default
    try:
        value = float(answer_row.get("min_proof_score", default))
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def proof_evaluation_hit(
    result: SolveResult,
    answer_row: dict[str, Any] | None = None,
    evaluation_mode: str = "proof_validity",
) -> bool:
    """Never auto-accept free-form proofs from structural/self-review signals alone.

    The rubric remains useful for triage, but semantic correctness is claim-bound and
    requires an external/manual review that this evaluator does not implement.
    """

    _ = answer_row, evaluation_mode
    if not is_semantically_successful(result) or result.final_answer.type != "proof":
        return False
    return False


def _proof_validity_hit(result: SolveResult) -> bool:
    return proof_evaluation_hit(result)


def proof_failure_category(
    result: SolveResult,
    answer_row: dict[str, Any] | None = None,
    evaluation_mode: str = "proof_validity",
) -> str:
    if result.final_answer.type != "proof":
        return "proof_wrong_answer_type"
    if not result.verification.passed:
        return "proof_verifier_failed"
    score = proof_quality_score(result)
    if score.proof_invalid:
        return "proof_quality_invalid"
    if score.score < _proof_min_score(answer_row, evaluation_mode):
        return "proof_quality_below_threshold"
    if score.proof_partial:
        return "proof_partial"
    return "proof_manual_review_required"


def _trace_budget_metrics(
    trace_dir: str | Path | None,
    eligible_question_ids: set[str] | None = None,
    eligible_results: dict[str, SolveResult] | None = None,
) -> dict[str, object]:
    if not trace_dir:
        return {}
    trace_result = read_trace_dir(trace_dir)
    safe_trace_dir = trace_result.get("trace_dir", "[redacted-path]")
    if not trace_result.get("ok"):
        return {
            "trace_dir": safe_trace_dir,
            "trace_read_ok": False,
            "trace_error": trace_result.get("error", {}),
        }

    trace_groups: dict[str, list[dict[str, Any]]] = {}
    unmatched_question_ids: set[str] = set()
    unmatched_count = 0
    missing_question_id_count = 0
    result_question_id_mismatch_ids: set[str] = set()
    result_question_id_mismatch_count = 0
    result_content_mismatch_ids: set[str] = set()
    result_content_mismatch_count = 0
    provenance_mismatch_ids: set[str] = set()
    provenance_mismatch_count = 0
    for item in trace_result.get("items", []):
        if not isinstance(item, dict) or not item.get("ok"):
            continue
        trace = item.get("trace")
        if not isinstance(trace, dict):
            continue
        raw_qid = trace.get("question_id")
        if not isinstance(raw_qid, str) or not raw_qid.strip():
            missing_question_id_count += 1
            continue
        question_id = raw_qid.strip()
        if (
            eligible_question_ids is not None
            and question_id not in eligible_question_ids
        ):
            unmatched_count += 1
            unmatched_question_ids.add(question_id)
            continue
        final_result = trace.get("final_result")
        if isinstance(final_result, dict) and "question_id" in final_result:
            final_question_id = final_result.get("question_id")
            if (
                not isinstance(final_question_id, str)
                or final_question_id.strip() != question_id
            ):
                result_question_id_mismatch_count += 1
                result_question_id_mismatch_ids.add(question_id)
                continue
        expected_result = (
            eligible_results.get(question_id) if eligible_results is not None else None
        )
        binding_required = bool(
            expected_result is not None
            and (
                expected_result.input_fingerprint
                or expected_result.execution_fingerprint
            )
        )
        if expected_result is not None and binding_required:
            try:
                traced_result = SolveResult.model_validate(final_result, strict=True)
            except ValidationError:
                result_content_mismatch_count += 1
                result_content_mismatch_ids.add(question_id)
                continue
            if traced_result.model_dump() != expected_result.model_dump():
                result_content_mismatch_count += 1
                result_content_mismatch_ids.add(question_id)
                continue
            if not is_valid_trace_audit_evidence(
                trace,
                expected_result,
                expected_real_mode=None,
            ):
                provenance_mismatch_count += 1
                provenance_mismatch_ids.add(question_id)
                continue
        trace_groups.setdefault(question_id, []).append(trace)

    duplicate_question_ids = {
        question_id for question_id, traces in trace_groups.items() if len(traces) > 1
    }
    traces_to_measure = [
        traces[0]
        for question_id, traces in sorted(trace_groups.items())
        if question_id not in duplicate_question_ids
    ]

    total_model_calls = 0
    total_tool_calls = 0
    total_latency = 0.0
    latency_count = 0
    stage_counter: Counter[str] = Counter()
    trace_count = 0
    tool_solved_count = 0
    model_solved_count = 0
    model_verified_count = 0
    tool_override_count = 0
    model_then_tool_final_count = 0
    for trace in traces_to_measure:
        trace_count += 1
        model_calls = trace.get("model_calls")
        tool_calls = trace.get("tool_calls")
        stages: list[str] = []
        if isinstance(model_calls, list):
            total_model_calls += len(model_calls)
            stages = [
                str(call.get("stage", "unknown"))
                for call in model_calls
                if isinstance(call, dict)
            ]
            stage_counter.update(stages)
        elif isinstance(trace.get("model_calls_count"), int):
            total_model_calls += int(trace["model_calls_count"])
        successful_tool_call = False
        if isinstance(tool_calls, list):
            total_tool_calls += len(tool_calls)
            successful_tool_call = any(
                isinstance(call, dict)
                and str(call.get("status", "")).lower() == "success"
                for call in tool_calls
            )
        latency = trace.get("latency_seconds")
        if isinstance(latency, (int, float)) and latency >= 0:
            total_latency += float(latency)
            latency_count += 1
        final_result = trace.get("final_result")
        final_status = ""
        verification_method = ""
        verification_passed = False
        final_value = ""
        final_error: Any = None
        if isinstance(final_result, dict):
            final_status = str(final_result.get("status", ""))
            final_error = final_result.get("error")
            final_answer = final_result.get("final_answer")
            if isinstance(final_answer, dict):
                final_value = str(final_answer.get("value", "")).strip()
            verification = final_result.get("verification")
            if isinstance(verification, dict):
                verification_method = str(verification.get("method", ""))
                verification_passed = verification.get("passed") is True
        is_success = bool(
            final_status == "success"
            and verification_passed
            and final_value
            and final_error is None
        )
        has_model_solver = "solver" in stages
        has_model_verifier = "verifier" in stages
        if is_success and successful_tool_call and not has_model_solver:
            tool_solved_count += 1
        if is_success and has_model_solver:
            model_solved_count += 1
        if is_success and has_model_verifier:
            model_verified_count += 1
        if (
            is_success
            and has_model_solver
            and successful_tool_call
            and verification_method
            in {"symbolic_check", "numeric_check", "substitution"}
        ):
            model_then_tool_final_count += 1
        final_answer_source = str(trace.get("final_answer_source", "")).strip().lower()
        explicit_override = trace.get(
            "tool_overrode_model"
        ) is True or final_answer_source in {"tool_override", "tool_overrode_model"}
        if (
            explicit_override
            and is_success
            and verification_passed
            and has_model_solver
            and successful_tool_call
        ):
            tool_override_count += 1

    return {
        "trace_dir": safe_trace_dir,
        "trace_read_ok": True,
        "trace_count": trace_count,
        "trace_eligible_question_id_count": (
            len(eligible_question_ids)
            if eligible_question_ids is not None
            else len(trace_groups)
        ),
        "trace_error_count": trace_result.get("error_count", 0),
        "trace_missing_question_id_count": missing_question_id_count,
        "trace_unmatched_count": unmatched_count,
        "trace_unmatched_question_ids": sorted(unmatched_question_ids),
        "trace_duplicate_question_id_count": len(duplicate_question_ids),
        "trace_duplicate_question_ids": sorted(duplicate_question_ids),
        "trace_result_question_id_mismatch_count": result_question_id_mismatch_count,
        "trace_result_question_id_mismatch_ids": sorted(
            result_question_id_mismatch_ids
        ),
        "trace_result_content_mismatch_count": result_content_mismatch_count,
        "trace_result_content_mismatch_ids": sorted(result_content_mismatch_ids),
        "trace_provenance_mismatch_count": provenance_mismatch_count,
        "trace_provenance_mismatch_ids": sorted(provenance_mismatch_ids),
        "trace_binding_integrity_ok": bool(
            trace_result.get("error_count", 0) == 0
            and missing_question_id_count == 0
            and unmatched_count == 0
            and not duplicate_question_ids
            and result_question_id_mismatch_count == 0
            and result_content_mismatch_count == 0
            and provenance_mismatch_count == 0
            and (
                eligible_question_ids is None
                or trace_count == len(eligible_question_ids)
            )
        ),
        "total_model_calls": total_model_calls,
        "total_tool_calls": total_tool_calls,
        "average_model_calls_per_trace": _safe_rate(total_model_calls, trace_count),
        "average_tool_calls_per_trace": _safe_rate(total_tool_calls, trace_count),
        "average_latency_seconds": _safe_rate(int(total_latency * 1000), latency_count)
        / 1000,
        "model_calls_by_stage": dict(sorted(stage_counter.items())),
        "tool_solved_count": tool_solved_count,
        "model_solved_count": model_solved_count,
        "model_verified_count": model_verified_count,
        "model_then_tool_final_count": model_then_tool_final_count,
        "tool_override_count": tool_override_count,
    }


def evaluate_results(
    results_path: str | Path,
    answers_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
) -> dict:
    results_source = Path(results_path)
    try:
        result_source_exists = (
            results_source.is_file()
            and not results_source.is_symlink()
            and not getattr(results_source, "is_junction", lambda: False)()
        )
        result_source_nonempty = (
            result_source_exists and results_source.stat().st_size > 0
        )
    except OSError:
        result_source_exists = False
        result_source_nonempty = False
    raw_rows, json_invalid = (
        load_jsonl(results_source) if result_source_exists else ([], 0)
    )
    answer_dataset = _load_answer_dataset(answers_path)
    answers = answer_dataset.answers
    answer_records = answer_dataset.records

    valid_results: list[SolveResult] = []
    schema_invalid = 0
    for row in raw_rows:
        try:
            valid_results.append(SolveResult.model_validate(row))
        except ValidationError:
            schema_invalid += 1

    result_groups: dict[str, list[SolveResult]] = {}
    invalid_question_id_count = 0
    for candidate_result in valid_results:
        question_id = str(candidate_result.question_id).strip()
        if not question_id:
            invalid_question_id_count += 1
            continue
        result_groups.setdefault(question_id, []).append(candidate_result)
    duplicate_result_ids = {
        question_id
        for question_id, results in result_groups.items()
        if len(results) > 1
    }
    duplicate_result_row_count = sum(
        max(0, len(results) - 1) for results in result_groups.values()
    )
    unique_results = {
        question_id: results[0]
        for question_id, results in result_groups.items()
        if len(results) == 1
    }
    gold_ids = set(answer_records)
    unexpected_result_ids = (
        set(result_groups) - gold_ids if answers_path is not None else set()
    )

    total = len(raw_rows) + json_invalid
    json_valid_count = len(valid_results)

    status_counter = Counter(r.status for r in valid_results)
    domain_counter = Counter(r.domain for r in valid_results)
    type_counter = Counter(r.problem_type for r in valid_results)

    verifier_pass = sum(1 for r in valid_results if r.verification.passed)
    avg_conf = (
        sum(r.confidence for r in valid_results) / json_valid_count
        if json_valid_count
        else 0.0
    )

    metrics: dict[str, object] = {
        "total": total,
        "result_source_exists": result_source_exists,
        "result_source_nonempty": result_source_nonempty,
        "json_valid_count": json_valid_count,
        "json_valid_rate": _safe_rate(json_valid_count, total),
        "json_invalid_count": total - json_valid_count,
        "json_schema_invalid_count": schema_invalid,
        "success_count": status_counter.get("success", 0),
        "partial_count": status_counter.get("partial", 0),
        "fail_count": status_counter.get("fail", 0),
        "verifier_pass_rate": _safe_rate(verifier_pass, json_valid_count),
        "average_confidence": avg_conf,
        "domain_distribution": dict(sorted(domain_counter.items())),
        "problem_type_distribution": dict(sorted(type_counter.items())),
        "invalid_question_id_count": invalid_question_id_count,
        "duplicate_result_id_count": len(duplicate_result_ids),
        "duplicate_result_row_count": duplicate_result_row_count,
        "duplicate_result_ids": sorted(duplicate_result_ids),
        "unexpected_result_id_count": len(unexpected_result_ids),
        "unexpected_result_ids": sorted(unexpected_result_ids),
    }
    metrics.update(_explanation_quality_metrics(valid_results))

    result_integrity_ok = not (
        not result_source_exists
        or not result_source_nonempty
        or json_invalid
        or schema_invalid
        or invalid_question_id_count
        or duplicate_result_ids
        or unexpected_result_ids
    )
    metrics["result_integrity_ok"] = result_integrity_ok

    eligible_trace_ids = set(unique_results)
    if answers_path is not None:
        eligible_trace_ids &= gold_ids - set(answer_dataset.duplicate_ids)
        missing_result_ids = sorted(gold_ids - set(result_groups))
        unscorable_result_ids = sorted(
            gold_ids
            & set(result_groups)
            & (duplicate_result_ids | set(answer_dataset.duplicate_ids))
        )
        exact = normalized = numeric = symbolic = matched_items = 0
        short_answer_expected = 0
        short_answer_covered = 0
        proof_validity_expected = 0
        proof_validity_covered = 0
        proof_validity_pass = 0
        proof_quality_sum = 0.0
        proof_complete = 0
        proof_partial = 0
        proof_invalid = 0
        proof_risk_counter: Counter[str] = Counter()
        evaluation_pass = 0
        by_domain: dict[str, dict[str, Any]] = {}
        by_problem_type: dict[str, dict[str, Any]] = {}
        for question_id in sorted(gold_ids):
            gold = answers[question_id]
            answer_row = answer_records[question_id]
            eval_mode = str(answer_row.get("evaluation_mode") or "short_answer")
            result = (
                unique_results.get(question_id)
                if question_id not in answer_dataset.duplicate_ids
                else None
            )
            if result is not None:
                matched_items += 1
            exact_hit = normalized_hit = numeric_hit = symbolic_hit = 0
            proof_hit = 0
            proof_score: ProofRubricScore | None = None
            if _is_proof_eval_mode(eval_mode):
                proof_validity_expected += 1
                if result is not None:
                    proof_validity_covered += 1
                    proof_score = proof_quality_score(result)
                    proof_quality_sum += proof_score.score
                    proof_complete += int(proof_score.proof_complete)
                    proof_partial += int(proof_score.proof_partial)
                    proof_invalid += int(proof_score.proof_invalid)
                    proof_risk_counter.update(proof_score.risk_flags)
                    proof_hit = int(proof_evaluation_hit(result, answer_row, eval_mode))
                    proof_validity_pass += proof_hit
                    evaluation_pass += proof_hit
            else:
                short_answer_expected += 1
                if result is not None:
                    short_answer_covered += 1
                    result_eligible = bool(
                        is_semantically_successful(result)
                        and is_canonical_final_answer(result.final_answer.value)
                    )
                    pred = result.final_answer.value
                    exact_hit = int(result_eligible and judge_exact_match(pred, gold))
                    normalized_hit = int(
                        result_eligible and normalized_match(pred, gold)
                    )
                    numeric_hit = int(result_eligible and numeric_match(pred, gold))
                    symbolic_hit = int(
                        result_eligible
                        and (
                            bool(normalized_hit)
                            or bool(numeric_hit)
                            or symbolic_match(pred, gold)
                        )
                    )
                    exact += exact_hit
                    normalized += normalized_hit
                    numeric += numeric_hit
                    symbolic += symbolic_hit
                    evaluation_pass += normalized_hit

            groups = [
                (
                    str(
                        answer_row.get("domain")
                        or (result.domain if result is not None else "unknown")
                        or "unknown"
                    ),
                    by_domain,
                ),
                (
                    str(
                        answer_row.get("problem_type")
                        or (result.problem_type if result is not None else "unknown")
                        or "unknown"
                    ),
                    by_problem_type,
                ),
            ]
            for group_name, bucket_map in groups:
                bucket = bucket_map.setdefault(group_name, _match_bucket())
                bucket["total"] += 1
                bucket["short_answer_count"] += int(not _is_proof_eval_mode(eval_mode))
                bucket["exact_match_count"] += exact_hit
                bucket["normalized_match_count"] += normalized_hit
                bucket["numeric_match_count"] += numeric_hit
                bucket["symbolic_match_count"] += symbolic_hit
                bucket["proof_validity_count"] += int(_is_proof_eval_mode(eval_mode))
                bucket["proof_validity_pass_count"] += proof_hit
                if proof_score is not None:
                    bucket["proof_quality_score_sum"] += proof_score.score
                    bucket["proof_complete_count"] += int(proof_score.proof_complete)
                    bucket["proof_partial_count"] += int(proof_score.proof_partial)
                    bucket["proof_invalid_count"] += int(proof_score.proof_invalid)
                bucket["evaluation_pass_count"] += (
                    proof_hit if _is_proof_eval_mode(eval_mode) else normalized_hit
                )

        metrics.update(
            {
                "gold_unique_count": len(gold_ids),
                "answer_expected_count": len(gold_ids),
                "answer_covered_count": matched_items,
                "answer_missing_count": len(missing_result_ids),
                "answer_unscorable_count": len(unscorable_result_ids),
                "answer_uncovered_count": len(gold_ids) - matched_items,
                "answer_coverage_rate": _safe_rate(matched_items, len(gold_ids)),
                "missing_result_ids": missing_result_ids,
                "unscorable_result_ids": unscorable_result_ids,
                "answer_source_exists": answer_dataset.source_exists,
                "answer_source_nonempty": answer_dataset.source_nonempty,
                "answer_json_invalid_count": answer_dataset.json_invalid_count,
                "answer_schema_invalid_count": answer_dataset.schema_invalid_count,
                "answer_invalid_id_count": answer_dataset.invalid_id_count,
                "answer_duplicate_id_count": len(answer_dataset.duplicate_ids),
                "answer_duplicate_row_count": answer_dataset.duplicate_row_count,
                "answer_duplicate_ids": sorted(answer_dataset.duplicate_ids),
                "answer_integrity_ok": answer_dataset.integrity_ok,
                "short_answer_expected_count": short_answer_expected,
                "short_answer_covered_count": short_answer_covered,
                "proof_validity_expected_count": proof_validity_expected,
                "proof_validity_covered_count": proof_validity_covered,
                "proof_validity_pass_count": proof_validity_pass,
                "proof_validity_rate": _safe_rate(
                    proof_validity_pass, proof_validity_expected
                ),
                "covered_proof_validity_rate": _safe_rate(
                    proof_validity_pass, proof_validity_covered
                ),
                "proof_quality_average": (
                    proof_quality_sum / proof_validity_expected
                    if proof_validity_expected
                    else 0.0
                ),
                "covered_proof_quality_average": (
                    proof_quality_sum / proof_validity_covered
                    if proof_validity_covered
                    else 0.0
                ),
                "proof_complete_count": proof_complete,
                "proof_partial_count": proof_partial,
                "proof_invalid_count": proof_invalid,
                "proof_risk_counts": dict(sorted(proof_risk_counter.items())),
                "evaluation_pass_count": evaluation_pass,
                "evaluation_pass_rate": _safe_rate(evaluation_pass, len(gold_ids)),
                "covered_evaluation_pass_rate": _safe_rate(
                    evaluation_pass, matched_items
                ),
                "exact_match": _safe_rate(exact, short_answer_expected),
                "normalized_match": _safe_rate(normalized, short_answer_expected),
                "numeric_match": _safe_rate(numeric, short_answer_expected),
                "symbolic_match": _safe_rate(symbolic, short_answer_expected),
                "covered_exact_match": _safe_rate(exact, short_answer_covered),
                "covered_normalized_match": _safe_rate(
                    normalized, short_answer_covered
                ),
                "covered_numeric_match": _safe_rate(numeric, short_answer_covered),
                "covered_symbolic_match": _safe_rate(symbolic, short_answer_covered),
                "answer_match_by_domain": _finalize_match_buckets(by_domain),
                "answer_match_by_problem_type": _finalize_match_buckets(
                    by_problem_type
                ),
            }
        )
        metrics["evaluation_integrity_ok"] = bool(
            answer_dataset.integrity_ok
            and result_integrity_ok
            and matched_items == len(gold_ids)
        )
    else:
        metrics["evaluation_integrity_ok"] = result_integrity_ok

    eligible_trace_results = {
        question_id: unique_results[question_id]
        for question_id in eligible_trace_ids
        if question_id in unique_results
    }
    trace_metrics = _trace_budget_metrics(
        trace_dir,
        eligible_trace_ids,
        eligible_trace_results,
    )
    metrics.update(trace_metrics)
    if trace_dir:
        metrics["evaluation_integrity_ok"] = bool(
            metrics.get("evaluation_integrity_ok") is True
            and trace_metrics.get("trace_binding_integrity_ok") is True
        )
    return metrics


def _format_rate(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _render_counter_table(title: str, values: dict[str, Any]) -> list[str]:
    lines = ["", f"## {title}", "", "| Name | Count |", "|---|---:|"]
    for key, value in values.items():
        lines.append(f"| {key} | {value} |")
    return lines


def _render_match_table(title: str, grouped: dict[str, Any]) -> list[str]:
    header = (
        "| Group | Total | Short | Exact | Exact Rate | Normalized | "
        "Normalized Rate | Numeric Rate | Symbolic Rate | Proof Valid | "
        "Proof Rate | Avg Proof Score | Proof Complete | Eval Pass Rate |"
    )
    row_template = (
        "| {group} | {total} | {short} | {exact} | {exact_rate} | {norm} | "
        "{norm_rate} | {num_rate} | {sym_rate} | {proof} | {proof_rate} | "
        "{proof_score} | {proof_complete} | {eval_rate} |"
    )
    lines = [
        "",
        f"## {title}",
        "",
        header,
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group_name, group_metrics in grouped.items():
        if not isinstance(group_metrics, dict):
            continue
        lines.append(
            row_template.format(
                group=group_name,
                total=group_metrics.get("total", 0),
                short=group_metrics.get("short_answer_count", 0),
                exact=group_metrics.get("exact_match_count", 0),
                exact_rate=_format_rate(group_metrics.get("exact_match_rate", 0.0)),
                norm=group_metrics.get("normalized_match_count", 0),
                norm_rate=_format_rate(group_metrics.get("normalized_match_rate", 0.0)),
                num_rate=_format_rate(group_metrics.get("numeric_match_rate", 0.0)),
                sym_rate=_format_rate(group_metrics.get("symbolic_match_rate", 0.0)),
                proof=group_metrics.get("proof_validity_pass_count", 0),
                proof_rate=_format_rate(group_metrics.get("proof_validity_rate", 0.0)),
                proof_score=_format_rate(
                    group_metrics.get("proof_quality_average", 0.0)
                ),
                proof_complete=group_metrics.get("proof_complete_count", 0),
                eval_rate=_format_rate(group_metrics.get("evaluation_pass_rate", 0.0)),
            )
        )
    return lines


def render_markdown_report(
    metrics: dict, results_path: str, answers_path: str | None = None
) -> str:
    lines = ["# Evaluation Report", "", f"- Results: `{results_path}`"]
    if answers_path:
        lines.append(f"- Answers: `{answers_path}`")
    lines.extend(["", "## Core Metrics"])

    keys = [
        "total",
        "json_valid_count",
        "json_valid_rate",
        "success_count",
        "partial_count",
        "fail_count",
        "verifier_pass_rate",
        "average_confidence",
        "result_integrity_ok",
        "evaluation_integrity_ok",
        "invalid_question_id_count",
        "duplicate_result_id_count",
        "unexpected_result_id_count",
    ]
    for k in keys:
        lines.append(f"- **{k}**: {metrics.get(k)}")

    lines.extend(["", "## Explanation Quality"])
    for k in [
        "explanation_checked_count",
        "visible_steps_nonempty_count",
        "visible_steps_nonempty_rate",
        "average_visible_step_count",
        "didactic_hint_nonempty_count",
        "didactic_hint_nonempty_rate",
        "didactic_hint_template_risk_count",
        "didactic_hint_template_risk_rate",
        "key_idea_coverage_count",
        "key_idea_coverage_rate",
    ]:
        lines.append(f"- **{k}**: {metrics.get(k)}")

    domain_distribution = metrics.get("domain_distribution", {})
    if isinstance(domain_distribution, dict):
        lines.extend(_render_counter_table("Domain Distribution", domain_distribution))

    problem_type_distribution = metrics.get("problem_type_distribution", {})
    if isinstance(problem_type_distribution, dict):
        lines.extend(
            _render_counter_table(
                "Problem Type Distribution", problem_type_distribution
            )
        )

    if "exact_match" in metrics:
        lines.extend(["", "## Answer Matching"])
        for k in [
            "answer_expected_count",
            "answer_covered_count",
            "answer_missing_count",
            "answer_unscorable_count",
            "answer_coverage_rate",
            "answer_integrity_ok",
            "answer_json_invalid_count",
            "answer_schema_invalid_count",
            "answer_invalid_id_count",
            "answer_duplicate_id_count",
            "short_answer_expected_count",
            "short_answer_covered_count",
            "proof_validity_expected_count",
            "proof_validity_covered_count",
            "proof_validity_pass_count",
            "proof_validity_rate",
            "proof_quality_average",
            "proof_complete_count",
            "proof_partial_count",
            "proof_invalid_count",
            "evaluation_pass_count",
            "evaluation_pass_rate",
            "covered_evaluation_pass_rate",
            "exact_match",
            "normalized_match",
            "numeric_match",
            "symbolic_match",
        ]:
            lines.append(f"- **{k}**: {metrics.get(k)}")
        proof_risk_counts = metrics.get("proof_risk_counts")
        if isinstance(proof_risk_counts, dict) and proof_risk_counts:
            lines.extend(_render_counter_table("Proof Risk Counts", proof_risk_counts))
        for section_title, key in [
            ("Answer Match by Domain", "answer_match_by_domain"),
            ("Answer Match by Problem Type", "answer_match_by_problem_type"),
        ]:
            grouped = metrics.get(key)
            if isinstance(grouped, dict) and grouped:
                lines.extend(_render_match_table(section_title, grouped))

    if metrics.get("trace_read_ok") is not None:
        average_model_calls = _format_rate(
            metrics.get("average_model_calls_per_trace", 0.0)
        )
        average_tool_calls = _format_rate(
            metrics.get("average_tool_calls_per_trace", 0.0)
        )
        average_latency = _format_rate(metrics.get("average_latency_seconds", 0.0))
        lines.extend(
            [
                "",
                "## Budget / Trace Metrics",
                "",
                "| Metric | Value |",
                "|---|---:|",
                f"| trace_read_ok | {metrics.get('trace_read_ok')} |",
                f"| trace_count | {metrics.get('trace_count', 0)} |",
                f"| trace_error_count | {metrics.get('trace_error_count', 0)} |",
                f"| trace_missing_question_id_count | {metrics.get('trace_missing_question_id_count', 0)} |",
                f"| trace_unmatched_count | {metrics.get('trace_unmatched_count', 0)} |",
                f"| trace_duplicate_question_id_count | {metrics.get('trace_duplicate_question_id_count', 0)} |",
                f"| total_model_calls | {metrics.get('total_model_calls', 0)} |",
                f"| total_tool_calls | {metrics.get('total_tool_calls', 0)} |",
                f"| tool_solved_count | {metrics.get('tool_solved_count', 0)} |",
                f"| model_solved_count | {metrics.get('model_solved_count', 0)} |",
                f"| model_verified_count | {metrics.get('model_verified_count', 0)} |",
                f"| model_then_tool_final_count | {metrics.get('model_then_tool_final_count', 0)} |",
                f"| tool_override_count | {metrics.get('tool_override_count', 0)} |",
                f"| average_model_calls_per_trace | {average_model_calls} |",
                f"| average_tool_calls_per_trace | {average_tool_calls} |",
                f"| average_latency_seconds | {average_latency} |",
            ]
        )
        stage_counts = metrics.get("model_calls_by_stage")
        if isinstance(stage_counts, dict) and stage_counts:
            lines.extend(_render_counter_table("Model Calls by Stage", stage_counts))

    return "\n".join(lines) + "\n"


def normalize_answer(text: Any) -> str:
    if text is None:
        return ""
    return normalize_answer_core(str(text)).lower()


def normalized_exact_match(pred: Any, expected: Any) -> bool:
    return normalize_answer(pred) == normalize_answer(expected)


def exact_match(pred: Any, expected: Any) -> bool:
    """Backward-compatible shadow-eval exact-match wrapper."""
    return normalized_exact_match(pred, expected)


def compute_json_valid_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("json_valid", False)) / len(results)


def compute_missing_final_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if not r.get("final_answer_exists", True)) / len(
        results
    )


def compute_dirty_boxed_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("dirty_boxed", False)) / len(results)


def compute_trace_coverage_rate(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("trace_exists", False)) / len(results)


def compute_failure_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(r.get("failure_category", "unknown")) for r in results)
    return dict(sorted(counter.items()))


def _summarize_dimension(results: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, dict[str, int]] = {}
    for r in results:
        k = str(r.get(key, "unknown") or "unknown")
        g = grouped.setdefault(k, {"total": 0, "exact_match_count": 0})
        g["total"] += 1
        g["exact_match_count"] += int(bool(r.get("exact_match", False)))
    out: dict[str, Any] = {}
    for name, d in sorted(grouped.items()):
        total = d["total"]
        out[name] = {
            "total": total,
            "exact_match_count": d["exact_match_count"],
            "exact_match_rate": d["exact_match_count"] / total if total else 0.0,
        }
    return out


def summarize_by_domain(results: list[dict[str, Any]]) -> dict[str, Any]:
    return _summarize_dimension(results, "domain")


def summarize_by_difficulty(results: list[dict[str, Any]]) -> dict[str, Any]:
    return _summarize_dimension(results, "difficulty")
