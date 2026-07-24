from .error_taxonomy import FailureCategory, classify_failure_taxonomy
from .failure_report import (
    build_failure_rows,
    classify_failure_report,
    render_failure_report,
    write_failure_report,
)
from .hard_mode_ablation import (
    HardModeAblationConfig,
    HardModeAblationReport,
    HardModeRunResult,
    build_ablation_config,
    compare_ablation_runs,
    render_hard_mode_ablation_report,
    run_hard_mode_ablation,
    run_single_level_ablation,
    write_hard_mode_ablation_outputs,
)
from .judge import exact_match as exact_match_judge
from .judge import normalized_match, numeric_match, symbolic_match
from .metrics import (
    accuracy,
    compute_dirty_boxed_rate,
    compute_failure_counts,
    compute_json_valid_rate,
    compute_missing_final_rate,
    compute_trace_coverage_rate,
    evaluate_results,
)
from .metrics import (
    exact_match as exact_match,  # normalized exact match (backward-compat)
)
from .metrics import (
    explanation_quality_for_result,
    load_answer_records,
    load_answers,
    load_jsonl,
    normalize_answer,
    normalized_exact_match,
    proof_evaluation_hit,
    proof_failure_category,
    proof_quality_score,
)
from .metrics import render_markdown_report as render_metrics_markdown_report
from .metrics import (
    summarize_by_difficulty,
    summarize_by_domain,
)
from .proof_review import (
    build_proof_review_rows,
    proof_review_feedback,
    render_proof_review_pack,
    write_proof_review_pack,
)
from .report import write_markdown_report
from .shadow_eval import (
    ShadowEvalCase,
    ShadowEvalResult,
    ShadowEvalSummary,
    load_cases,
)
from .shadow_eval import render_markdown_report as render_shadow_eval_markdown_report
from .shadow_eval import (
    run_shadow_eval,
    summarize_results,
    write_jsonl,
    write_summary,
)

__all__ = [
    # error_taxonomy
    "FailureCategory",
    "classify_failure_taxonomy",
    # failure_report
    "build_failure_rows",
    "classify_failure_report",
    "render_failure_report",
    "write_failure_report",
    # hard_mode_ablation
    "HardModeAblationConfig",
    "HardModeAblationReport",
    "HardModeRunResult",
    "build_ablation_config",
    "compare_ablation_runs",
    "render_hard_mode_ablation_report",
    "run_hard_mode_ablation",
    "run_single_level_ablation",
    "write_hard_mode_ablation_outputs",
    # judge
    "exact_match_judge",
    "normalized_match",
    "numeric_match",
    "symbolic_match",
    # metrics
    "accuracy",
    "compute_dirty_boxed_rate",
    "compute_failure_counts",
    "compute_json_valid_rate",
    "compute_missing_final_rate",
    "compute_trace_coverage_rate",
    "evaluate_results",
    "exact_match",  # normalized exact match (metrics.py)
    "explanation_quality_for_result",
    "load_answer_records",
    "load_answers",
    "load_jsonl",
    "normalized_exact_match",
    "normalize_answer",
    "proof_evaluation_hit",
    "proof_failure_category",
    "proof_quality_score",
    "render_metrics_markdown_report",
    "summarize_by_difficulty",
    "summarize_by_domain",
    # proof_review
    "build_proof_review_rows",
    "proof_review_feedback",
    "render_proof_review_pack",
    "write_proof_review_pack",
    # report
    "write_markdown_report",
    # shadow_eval
    "ShadowEvalCase",
    "ShadowEvalResult",
    "ShadowEvalSummary",
    "load_cases",
    "render_shadow_eval_markdown_report",
    "run_shadow_eval",
    "summarize_results",
    "write_jsonl",
    "write_summary",
]
