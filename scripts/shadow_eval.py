from __future__ import annotations

import argparse
from pathlib import Path

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.evaluation.report import write_markdown_report
from math_agent.evaluation.shadow_eval import (
    load_cases,
    run_shadow_eval,
    summarize_results,
    write_jsonl,
    write_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run mock/shadow evaluation (non-official)."
    )
    parser.add_argument("--input", default=None)
    parser.add_argument("--out", default="outputs/shadow_eval")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--mock", action="store_true", default=True)
    parser.add_argument("--no-trace", action="store_true")
    parser.add_argument("--enable-tools", action="store_true")
    parser.add_argument("--mode", choices=["fast", "full"], default="fast")
    parser.add_argument("--fail-on-format-error", action="store_true")
    parser.add_argument("--fail-on-missing-final", action="store_true")
    parser.add_argument("--fail-on-dirty-boxed", action="store_true")
    args = parser.parse_args()

    cases = load_cases(args.input, limit=args.limit)

    results = run_shadow_eval(cases, options={"mock": args.mock, "mode": args.mode})
    summary = summarize_results(results)

    out_dir = Path(args.out)
    write_jsonl(results, out_dir / "shadow_results.jsonl")
    write_summary(summary, out_dir / "shadow_summary.json")
    write_markdown_report(summary, results, out_dir / "shadow_report.md")

    print(
        f"shadow_eval done: total={summary.total} exact_match={summary.exact_match_count}"
    )

    if args.fail_on_format_error and any(
        r.failure_category == "json_invalid" for r in results
    ):
        return 2
    if args.fail_on_missing_final and summary.missing_final_count > 0:
        return 3
    if args.fail_on_dirty_boxed and summary.dirty_boxed_count > 0:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
