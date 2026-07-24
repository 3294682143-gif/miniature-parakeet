from __future__ import annotations

import argparse

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.evaluation.proof_review import write_proof_review_pack


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a proof manual-review pack from results, answers, and traces."
    )
    parser.add_argument("--results", required=True, help="Path to results.jsonl")
    parser.add_argument("--answers", default=None, help="Optional answers.jsonl")
    parser.add_argument("--trace-dir", default=None, help="Optional trace directory")
    parser.add_argument(
        "--out",
        default="outputs/proof_manual_review_pack.md",
        help="Output markdown report path",
    )
    args = parser.parse_args()
    rows = write_proof_review_pack(
        results_path=args.results,
        answers_path=args.answers,
        trace_dir=args.trace_dir,
        out_path=args.out,
    )
    review_count = sum(1 for row in rows if row.get("manual_review_recommended"))
    print(f"proof_count={len(rows)}")
    print(f"manual_review_recommended_count={review_count}")
    print(f"report={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
