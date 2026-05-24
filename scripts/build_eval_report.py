from __future__ import annotations

import argparse
import json
from pathlib import Path

from math_agent.evaluation.report import write_markdown_report
from math_agent.evaluation.shadow_eval import ShadowEvalResult, summarize_results, write_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build shadow summary/report from shadow_results.jsonl")
    parser.add_argument("--results", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    rows: list[ShadowEvalResult] = []
    for line in Path(args.results).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(ShadowEvalResult(**json.loads(line)))

    summary = summarize_results(rows)
    out_dir = Path(args.out_dir)
    write_summary(summary, out_dir / "shadow_summary.json")
    write_markdown_report(summary, rows, out_dir / "shadow_report.md")
    print(f"report built: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
