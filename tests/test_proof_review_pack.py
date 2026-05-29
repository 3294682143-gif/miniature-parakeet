from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from math_agent.evaluation.proof_review import (
    build_proof_review_rows,
    write_proof_review_pack,
)


def _proof_result(qid: str, steps: list[str]) -> dict:
    return {
        "question_id": qid,
        "domain": "proof",
        "problem_type": "proof",
        "problem_parse": {"goal": "g", "givens": [], "symbols": []},
        "solution_plan": [],
        "visible_solution_steps": steps,
        "tool_trace": [],
        "final_answer": {"type": "proof", "value": "Proved.", "boxed": ""},
        "verification": {"method": "logic_review", "passed": True, "notes": "ok"},
        "didactic_hint": "Use the theorem and explain each implication.",
        "confidence": 0.8,
        "status": "success",
        "error": None,
    }


def test_proof_review_pack_exports_full_text_and_rubric(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    answers = tmp_path / "answers.jsonl"
    traces = tmp_path / "traces"
    traces.mkdir()
    strong_steps = [
        (
            "Let n be arbitrary. Since n=2k, then n^2=4k^2; therefore n^2 "
            "is even. This proves the claim."
        )
    ]
    weak_steps = ["Clearly true."]
    rows = [
        _proof_result("proof_ok", strong_steps),
        _proof_result("proof_weak", weak_steps),
    ]
    results.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    answers.write_text(
        "\n".join(
            json.dumps(
                {
                    "question_id": row["question_id"],
                    "answer": "proved",
                    "evaluation_mode": "proof_quality",
                    "min_proof_score": 0.68,
                },
                ensure_ascii=False,
            )
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )
    (traces / "proof_ok.json").write_text(
        json.dumps({"question": "Prove the claim."}, ensure_ascii=False),
        encoding="utf-8",
    )

    review_rows = build_proof_review_rows(results, answers, traces)
    assert len(review_rows) == 2
    assert review_rows[0]["proof_text"].startswith("Let n be arbitrary")
    assert "rubric_reasons" in review_rows[0]
    assert any(row["manual_review_recommended"] for row in review_rows)

    out = tmp_path / "proof_pack.md"
    write_proof_review_pack(results, out, answers, traces)
    text = out.read_text(encoding="utf-8")
    assert "Proof Manual Review Pack" in text
    assert "```text" in text
    assert out.with_suffix(".json").exists()


def test_proof_review_script_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/build_proof_review_pack.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--trace-dir" in proc.stdout
