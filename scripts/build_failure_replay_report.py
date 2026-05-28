from __future__ import annotations

import argparse

from math_agent.evaluation.failure_report import write_failure_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a failure-oriented replay report from results, answers, and traces."
    )
    parser.add_argument("--results", required=True, help="Path to results.jsonl")
    parser.add_argument("--answers", default=None, help="Optional answers.jsonl")
    parser.add_argument("--trace-dir", default=None, help="Optional trace directory")
    parser.add_argument(
        "--out",
        default="outputs/failure_replay_report.md",
        help="Output markdown report path",
    )
    parser.add_argument(
        "--exclude-format-only",
        action="store_true",
        help="Ignore exact-format mismatches when normalized answers match.",
    )
    args = parser.parse_args()
    rows = write_failure_report(
        results_path=args.results,
        answers_path=args.answers,
        trace_dir=args.trace_dir,
        out_path=args.out,
        include_format_only=not args.exclude_format_only,
    )
    print(f"failure_count={len(rows)}")
    print(f"report={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
