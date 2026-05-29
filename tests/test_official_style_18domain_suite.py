from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from scripts.generate_official_style_18domain_112 import DOMAIN_COUNTS, build_cases


def test_official_style_18domain_generator_shape() -> None:
    cases = build_cases()
    assert len(cases) == 112
    assert Counter(case.domain for case in cases) == DOMAIN_COUNTS
    assert len({case.domain for case in cases}) == 18
    assert all(case.question_id.startswith("os18_") for case in cases)
    assert all(case.question and case.answer for case in cases)
    assert any(case.evaluation_mode == "proof_quality" for case in cases)


def test_official_style_18domain_dataset_present_and_labeled() -> None:
    questions = [
        json.loads(line)
        for line in open("data/official_style_18domain_112.jsonl", encoding="utf-8")
        if line.strip()
    ]
    answers = [
        json.loads(line)
        for line in open(
            "data/official_style_18domain_112_answers.jsonl", encoding="utf-8"
        )
        if line.strip()
    ]
    assert len(questions) == len(answers) == 112
    assert {row["domain"] for row in answers} == set(DOMAIN_COUNTS)
    assert all("Synthetic" in row["source"] for row in answers)
    assert all("not official" in row["source"] for row in answers)


def test_official_style_18domain_generator_writes_jsonl(tmp_path: Path) -> None:
    questions = tmp_path / "questions.jsonl"
    answers = tmp_path / "answers.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/generate_official_style_18domain_112.py",
            "--questions",
            str(questions),
            "--answers",
            str(answers),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "generated=112" in proc.stdout
    assert len(questions.read_text(encoding="utf-8").splitlines()) == 112
    assert len(answers.read_text(encoding="utf-8").splitlines()) == 112
