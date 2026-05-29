from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from math_agent.evaluation.judge import exact_match as judge_exact_match
from math_agent.evaluation.judge import normalized_match, numeric_match, symbolic_match
from math_agent.harness.trace_reader import read_trace_dir
from math_agent.proof import ProofRubricScore, score_proof_candidate
from math_agent.schemas import SolveResult
from math_agent.tools.answer_normalizer import normalize_answer as normalize_answer_core


def accuracy(correct: int, total: int) -> float:
    return correct / total if total else 0.0


def _safe_rate(n: int, d: int) -> float:
    return n / d if d else 0.0


def load_jsonl(path: str | Path) -> tuple[list[dict], int]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return [], 0

    rows: list[dict] = []
    invalid = 0
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                invalid += 1
    return rows, invalid


def load_answers(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    rows, _ = load_jsonl(path)
    answers: dict[str, str] = {}
    for row in rows:
        qid = str(row.get("question_id", "")).strip()
        ans = str(row.get("answer", ""))
        if qid:
            answers[qid] = ans
    return answers


def load_answer_records(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    rows, _ = load_jsonl(path)
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = str(row.get("question_id", "")).strip()
        if qid:
            records[qid] = row
    return records


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
    if (
        result.status != "success"
        or result.final_answer.type != "proof"
        or not result.verification.passed
        or not result.final_answer.value.strip()
    ):
        return False
    score = proof_quality_score(result)
    return (not score.proof_invalid) and score.score >= _proof_min_score(
        answer_row, evaluation_mode
    )


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
    return "proof_validity_failed"


def _trace_budget_metrics(trace_dir: str | Path | None) -> dict[str, object]:
    if not trace_dir:
        return {}
    trace_result = read_trace_dir(trace_dir)
    if not trace_result.get("ok"):
        return {
            "trace_dir": str(trace_dir),
            "trace_read_ok": False,
            "trace_error": trace_result.get("error", {}),
        }

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
    for item in trace_result.get("items", []):
        if not item.get("ok"):
            continue
        trace = item.get("trace") or {}
        if not isinstance(trace, dict):
            continue
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
        if isinstance(final_result, dict):
            final_status = str(final_result.get("status", ""))
            verification = final_result.get("verification")
            if isinstance(verification, dict):
                verification_method = str(verification.get("method", ""))
        is_success = final_status == "success"
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
            tool_override_count += 1

    return {
        "trace_dir": str(trace_dir),
        "trace_read_ok": True,
        "trace_count": trace_count,
        "trace_error_count": trace_result.get("error_count", 0),
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
        "tool_override_count": tool_override_count,
    }


def evaluate_results(
    results_path: str | Path,
    answers_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
) -> dict:
    raw_rows, json_invalid = load_jsonl(results_path)
    answers = load_answers(answers_path)
    answer_records = load_answer_records(answers_path)

    valid_results: list[SolveResult] = []
    schema_invalid = 0
    for row in raw_rows:
        try:
            valid_results.append(SolveResult.model_validate(row))
        except ValidationError:
            schema_invalid += 1

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
    }
    metrics.update(_explanation_quality_metrics(valid_results))

    if answers:
        exact = normalized = numeric = symbolic = matched_items = 0
        short_answer_items = 0
        proof_validity_items = 0
        proof_validity_pass = 0
        proof_quality_sum = 0.0
        proof_complete = 0
        proof_partial = 0
        proof_invalid = 0
        proof_risk_counter: Counter[str] = Counter()
        evaluation_pass = 0
        by_domain: dict[str, dict[str, Any]] = {}
        by_problem_type: dict[str, dict[str, Any]] = {}
        for r in valid_results:
            gold = answers.get(r.question_id)
            if gold is None:
                continue
            matched_items += 1
            pred = r.final_answer.value
            answer_row = answer_records.get(r.question_id, {})
            eval_mode = str(answer_row.get("evaluation_mode") or "short_answer")
            exact_hit = normalized_hit = numeric_hit = symbolic_hit = 0
            proof_hit = 0
            proof_score: ProofRubricScore | None = None
            if _is_proof_eval_mode(eval_mode):
                proof_validity_items += 1
                proof_score = proof_quality_score(r)
                proof_quality_sum += proof_score.score
                proof_complete += int(proof_score.proof_complete)
                proof_partial += int(proof_score.proof_partial)
                proof_invalid += int(proof_score.proof_invalid)
                proof_risk_counter.update(proof_score.risk_flags)
                proof_hit = int(proof_evaluation_hit(r, answer_row, eval_mode))
                proof_validity_pass += proof_hit
                evaluation_pass += proof_hit
            else:
                short_answer_items += 1
                exact_hit = int(judge_exact_match(pred, gold))
                normalized_hit = int(normalized_match(pred, gold))
                numeric_hit = int(numeric_match(pred, gold))
                symbolic_hit = int(symbolic_match(pred, gold))
                exact += exact_hit
                normalized += normalized_hit
                numeric += numeric_hit
                symbolic += symbolic_hit
                evaluation_pass += normalized_hit

            groups = [
                (str(answer_row.get("domain") or r.domain or "unknown"), by_domain),
                (
                    str(answer_row.get("problem_type") or r.problem_type or "unknown"),
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
                "answer_covered_count": matched_items,
                "short_answer_covered_count": short_answer_items,
                "proof_validity_covered_count": proof_validity_items,
                "proof_validity_pass_count": proof_validity_pass,
                "proof_validity_rate": _safe_rate(
                    proof_validity_pass, proof_validity_items
                ),
                "proof_quality_average": (
                    proof_quality_sum / proof_validity_items
                    if proof_validity_items
                    else 0.0
                ),
                "proof_complete_count": proof_complete,
                "proof_partial_count": proof_partial,
                "proof_invalid_count": proof_invalid,
                "proof_risk_counts": dict(sorted(proof_risk_counter.items())),
                "evaluation_pass_count": evaluation_pass,
                "evaluation_pass_rate": _safe_rate(evaluation_pass, matched_items),
                "exact_match": _safe_rate(exact, short_answer_items),
                "normalized_match": _safe_rate(normalized, short_answer_items),
                "numeric_match": _safe_rate(numeric, short_answer_items),
                "symbolic_match": _safe_rate(symbolic, short_answer_items),
                "answer_match_by_domain": _finalize_match_buckets(by_domain),
                "answer_match_by_problem_type": _finalize_match_buckets(
                    by_problem_type
                ),
            }
        )

    metrics.update(_trace_budget_metrics(trace_dir))
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
            "answer_covered_count",
            "short_answer_covered_count",
            "proof_validity_covered_count",
            "proof_validity_pass_count",
            "proof_validity_rate",
            "proof_quality_average",
            "proof_complete_count",
            "proof_partial_count",
            "proof_invalid_count",
            "evaluation_pass_count",
            "evaluation_pass_rate",
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
                f"| total_model_calls | {metrics.get('total_model_calls', 0)} |",
                f"| total_tool_calls | {metrics.get('total_tool_calls', 0)} |",
                f"| tool_solved_count | {metrics.get('tool_solved_count', 0)} |",
                f"| model_solved_count | {metrics.get('model_solved_count', 0)} |",
                f"| model_verified_count | {metrics.get('model_verified_count', 0)} |",
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
