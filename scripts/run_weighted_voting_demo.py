from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.logging_utils import safe_text_write
from math_agent.verification.verifier_scoring import score_candidates, score_to_metadata
from math_agent.verification.weighted_voting import decision_to_metadata, weighted_vote


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs/weighted_voting_demo")
    ap.add_argument("--format", choices=["json", "markdown"], default="json")
    ap.add_argument("--fail-on-no-selection", action="store_true")
    a = ap.parse_args()
    c = [
        {"candidate_id": "c0", "source": "solver", "final_answer_value": "5"},
        {"candidate_id": "c1", "source": "repair", "final_answer_value": "\\boxed{5}"},
        {
            "candidate_id": "c2",
            "source": "tool",
            "final_answer_value": "6",
            "verification_method": "sympy",
        },
    ]
    s = score_candidates(c)
    d = weighted_vote(c, s)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "scores": [score_to_metadata(x) for x in s],
        "decision": decision_to_metadata(d),
    }
    safe_text_write(
        json.dumps(payload, ensure_ascii=False, indent=2),
        out / "weighted_voting_demo.json",
    )
    safe_text_write(
        f"# Weighted Voting Demo\n\nSelected: {d.selected_candidate_id}\n",
        out / "weighted_voting_demo.md",
    )
    if a.fail_on_no_selection and d.selected_candidate_id is None:
        raise SystemExit(1)
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
