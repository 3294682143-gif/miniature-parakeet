from __future__ import annotations

import argparse

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.debugger.failure_attribution import (
    build_debugger_report,
    load_shadow_results,
    select_representatives,
    write_debugger_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug shadow eval failures")
    parser.add_argument("--results", required=True)
    parser.add_argument("--summary")
    parser.add_argument("--out-dir", default="outputs/debug_shadow")
    parser.add_argument("--limit-representatives", type=int, default=10)
    parser.add_argument("--fail-on-p0", action="store_true")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    cases = load_shadow_results(args.results)
    report = build_debugger_report(cases)
    report.representative_failures = select_representatives(
        report.representative_failures, args.limit_representatives
    )
    write_debugger_outputs(report, args.out_dir)
    top_failure = (
        max(report.failure_category_counts.items(), key=lambda x: x[1])[0]
        if report.failure_category_counts
        else "none"
    )
    print(
        f"total={report.total} failed_count={report.failed_count} "
        f"p0_count={len(report.p0_actions)} top_failure_category={top_failure}"
    )
    return 1 if args.fail_on_p0 and report.p0_actions else 0


if __name__ == "__main__":
    raise SystemExit(main())
