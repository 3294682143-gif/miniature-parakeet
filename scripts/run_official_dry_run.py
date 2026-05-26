from __future__ import annotations

import argparse
import json
import sys

from math_agent.submission.dry_run import (
    build_dry_run_config,
    command_string,
    run_official_dry_run,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Official-like preofficial dry-run harness")
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", default="outputs/official_dry_run")
    p.add_argument("--results-name", default="dry_run_results.jsonl")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--mode", choices=["fast", "full"], default="fast")
    p.add_argument("--enable-tools", action="store_true", default=False)
    p.add_argument("--mock", action="store_true", default=True)
    p.add_argument("--real", action="store_true", default=False)
    p.add_argument("--allow-real", action="store_true", default=False)
    p.add_argument("--hard-mode", action="store_true", default=False)
    p.add_argument(
        "--hard-mode-level",
        choices=["off", "light", "standard", "strict"],
        default="standard",
    )
    p.add_argument("--trace-dir", default=None)
    p.add_argument("--no-trace", action="store_true", default=False)
    p.add_argument("--fail-on-invalid", action="store_true", default=False)
    p.add_argument("--fail-on-missing-final", action="store_true", default=False)
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        config = build_dry_run_config(
            input_path=args.input,
            out_dir=args.out_dir,
            results_name=args.results_name,
            mode=args.mode,
            enable_tools=args.enable_tools,
            mock=args.mock,
            real=args.real,
            allow_real=args.allow_real,
            hard_mode=args.hard_mode,
            hard_mode_level=args.hard_mode_level,
            save_trace=not args.no_trace,
            trace_dir=args.trace_dir,
            limit=args.limit,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    summary = run_official_dry_run(config, command=command_string(sys.argv))
    if args.format == "json":
        print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2))
    else:
        print(f"run_id: {summary.run_id}")
        print(f"results: {summary.results_path}")
        print(f"report: {summary.report_path}")

    if args.fail_on_invalid and summary.invalid_count > 0:
        return 3
    if args.fail_on_missing_final and summary.missing_final_count > 0:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
