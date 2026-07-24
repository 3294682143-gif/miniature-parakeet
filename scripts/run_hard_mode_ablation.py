from __future__ import annotations

import argparse
import json

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.evaluation.hard_mode_ablation import (
    build_ablation_config,
    run_hard_mode_ablation,
    write_hard_mode_ablation_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run hard-mode ablation on mock/shadow eval outputs (NOT official)."
    )
    parser.add_argument("--input", default=None)
    parser.add_argument("--out-dir", default="outputs/hard_mode_ablation")
    parser.add_argument("--levels", default="off,light,standard,strict")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--include-debugger", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--mock", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fail-on-p0", action="store_true")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()
    if not args.mock:
        parser.error("--no-mock is unsupported; ablation is local mock evidence only")

    cfg = build_ablation_config(
        levels=[x.strip() for x in args.levels.split(",") if x.strip()],
        limit=args.limit,
        input_path=args.input,
        include_debugger=args.include_debugger,
        out_dir=args.out_dir,
        mock=args.mock,
    )
    report = run_hard_mode_ablation(cfg)
    write_hard_mode_ablation_outputs(report, cfg.out_dir)

    if args.format == "json":
        print(json.dumps(report.comparison, ensure_ascii=False, indent=2))
    else:
        print(
            f"hard-mode ablation done: levels={','.join(report.levels)} total_cases={report.total_cases}"
        )
        print("NOT official evaluation; mock/shadow/ablation evidence only.")

    if args.fail_on_p0:
        p0 = sum(
            (r.debugger_summary or {}).get("p0_action_count", 0) for r in report.runs
        )
        if p0 > 0:
            return 10
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
