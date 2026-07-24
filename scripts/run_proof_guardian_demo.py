from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.logging_utils import safe_text_write
from math_agent.proof import build_proof_guardian_decision, score_proof_candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="outputs/proof_guardian_demo")
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    candidates = [
        {
            "candidate_id": "c1",
            "final_answer_value": "设 a,b 为偶数，因为 a=2m,b=2n，所以 a+b=2(m+n)，故为偶数。证毕。",
        },
        {"candidate_id": "c2", "final_answer_value": "偶数加偶数还是偶数。"},
        {
            "candidate_id": "c3",
            "final_answer_value": "假设成立，同时不成立，得到矛盾所以命题成立。",
        },
    ]
    scores = score_proof_candidates(candidates)
    decision = build_proof_guardian_decision(scores)
    payload = {"scores": [s.__dict__ for s in scores], "decision": decision.__dict__}
    safe_text_write(
        json.dumps(payload, ensure_ascii=False, indent=2),
        out / "proof_guardian_demo.json",
    )
    safe_text_write(
        "# Proof Guardian Demo\n\n```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```\n",
        out / "proof_guardian_demo.md",
    )


if __name__ == "__main__":
    main()
