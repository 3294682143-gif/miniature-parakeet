from __future__ import annotations

import argparse

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.evidence import build_demo_evidence_pack, write_demo_evidence_pack

CRITICAL_SOURCES = {"hard_mode_ablation", "official_dry_run"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate demo evidence pack (NOT official evaluation)."
    )
    parser.add_argument("--out-dir", default="outputs/demo_pack")
    parser.add_argument("--shadow-dir", default=None)
    parser.add_argument("--debugger-dir", default=None)
    parser.add_argument("--ablation-dir", default=None)
    parser.add_argument("--proof-dir", default=None)
    parser.add_argument("--dry-run-dir", default=None)
    parser.add_argument("--project-health-json", default=None)
    parser.add_argument("--limit-cases", type=int, default=12)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--fail-on-missing-critical", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pack = build_demo_evidence_pack(
        shadow_dir=args.shadow_dir,
        debugger_dir=args.debugger_dir,
        ablation_dir=args.ablation_dir,
        proof_dir=args.proof_dir,
        dry_run_dir=args.dry_run_dir,
        project_health_json=args.project_health_json,
        limit_cases=args.limit_cases,
    )
    write_demo_evidence_pack(pack=pack, out_dir=args.out_dir, output_format=args.format)

    missing_critical = [
        s.name for s in pack.sources if (s.name in CRITICAL_SOURCES and not s.exists)
    ]

    print(f"out_dir={args.out_dir}")
    print(f"source_count={len(pack.sources)}")
    print(f"demo_case_count={len(pack.demo_cases)}")
    print(f"warning_count={len(pack.warnings)}")
    print(pack.official_warning)

    if args.fail_on_missing_critical and missing_critical:
        print("missing_critical=" + ",".join(missing_critical))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
