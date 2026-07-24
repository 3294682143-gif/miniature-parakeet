from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.evaluation.metrics import evaluate_results, render_markdown_report
from math_agent.logging_utils import safe_text_write


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate results.jsonl and generate metrics/report."
    )
    parser.add_argument("--results", required=True, help="Path to results.jsonl")
    parser.add_argument("--answers", default=None, help="Path to answers.jsonl")
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional trace directory used to add model-call and latency metrics.",
    )
    parser.add_argument(
        "--report",
        default="outputs/evaluation_report.md",
        help="Output markdown report path",
    )
    args = parser.parse_args()

    metrics = evaluate_results(args.results, args.answers, args.trace_dir)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    report = render_markdown_report(metrics, args.results, args.answers)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    safe_text_write(report, report_path)
    print(f"Markdown report written to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
