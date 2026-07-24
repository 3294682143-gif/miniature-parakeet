from __future__ import annotations

import argparse
from pathlib import Path

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.evaluation.report import write_markdown_report
from math_agent.evaluation.shadow_eval import (
    ShadowEvalResult,
    summarize_results,
    write_summary,
)
from math_agent.io_utils import load_bounded_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build shadow summary/report from saved results"
    )
    parser.add_argument("--results", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    raw_rows, _ = load_bounded_jsonl(args.results, require_objects=True)
    rows = [ShadowEvalResult(**row) for row in raw_rows]

    summary = summarize_results(rows)
    out_dir = Path(args.out_dir)
    write_summary(summary, out_dir / "shadow_summary.json")
    write_markdown_report(summary, rows, out_dir / "shadow_report.md")
    print(f"report built: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
