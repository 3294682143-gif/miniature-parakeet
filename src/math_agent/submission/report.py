from __future__ import annotations

from pathlib import Path

from .dry_run import DryRunConfig, DryRunItemResult, DryRunSummary


def render_dry_run_report(
    summary: DryRunSummary, config: DryRunConfig, item_results: list[DryRunItemResult]
) -> str:
    errors = [r for r in item_results if r.error][:5]
    return f"""# Official-like Dry Run Report

This is NOT official evaluation.
This report is for preofficial / dry-run validation only.
Do not claim official accuracy from this report.
Do not rename dry_run_results.jsonl to official_results.jsonl.

## 1. Summary
- run_id: {summary.run_id}
- total: {summary.total}
- success: {summary.success_count}
- fail: {summary.fail_count}

## 2. Run Config
- input_path: {config.input_path}
- out_dir: {config.out_dir}
- mode: {config.mode}
- mock: {config.mock}
- real: {config.real}

## 3. Result Counts
- invalid_count: {summary.invalid_count}
- json_valid_count: {summary.json_valid_count}

## 4. Invalid Cases
- count: {summary.invalid_count}

## 5. Missing Final Answers
- missing_final_count: {summary.missing_final_count}

## 6. Trace Coverage
- save_trace: {config.save_trace}
- trace_dir: {summary.trace_dir}

## 7. Latency
- average_latency_ms: {summary.average_latency_ms:.2f}

## 8. Error Samples
{chr(10).join(f'- {e.question_id}: {e.error}' for e in errors) or '- none'}

## 9. Hard Mode Settings
- hard_mode: {config.hard_mode}
- hard_mode_level: {config.hard_mode_level}

## 10. Safety Notes
- No .env content is read by this harness.
- No token/api key fields are written by this harness.

## 11. Official Submission Warning
{summary.official_warning}

## 12. Next Steps
- Review invalid/error cases.
- Validate locally before any official submission workflow.
"""


def write_report(path: Path | str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")
