from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from scripts.generate_hard_hidden_math import build_cases


def test_hard_hidden_generator_balanced_and_interleaved() -> None:
    cases = build_cases()
    assert len(cases) == 120
    assert Counter(case.domain for case in cases) == {
        "proof": 40,
        "number_theory": 40,
        "geometry": 40,
    }
    assert Counter(case.evaluation_mode for case in cases) == {
        "proof_validity": 40,
        "short_answer": 80,
    }
    assert [case.domain for case in cases[:6]] == [
        "proof",
        "number_theory",
        "geometry",
        "proof",
        "number_theory",
        "geometry",
    ]
    assert all(case.question_id and case.question and case.answer for case in cases)


def test_hard_hidden_large_profile_has_300_plus_quality_items() -> None:
    cases = build_cases(profile="large")
    assert len(cases) == 360
    assert Counter(case.domain for case in cases) == {
        "proof": 120,
        "number_theory": 120,
        "geometry": 120,
    }
    assert Counter(case.evaluation_mode for case in cases) == {
        "proof_quality": 120,
        "short_answer": 240,
    }
    assert all(
        case.min_proof_score == 0.68
        for case in cases
        if case.evaluation_mode == "proof_quality"
    )
    assert [case.domain for case in cases[:6]] == [
        "proof",
        "number_theory",
        "geometry",
        "proof",
        "number_theory",
        "geometry",
    ]


def test_hard_hidden_generator_writes_official_like_jsonl(tmp_path: Path) -> None:
    questions = tmp_path / "hard_questions.jsonl"
    answers = tmp_path / "hard_answers.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/generate_hard_hidden_math.py",
            "--questions",
            str(questions),
            "--answers",
            str(answers),
            "--profile",
            "compact",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "generated=120" in proc.stdout
    question_rows = [
        json.loads(line) for line in questions.read_text(encoding="utf-8").splitlines()
    ]
    answer_rows = [
        json.loads(line) for line in answers.read_text(encoding="utf-8").splitlines()
    ]
    assert len(question_rows) == len(answer_rows) == 120
    assert set(question_rows[0]) == {"question_id", "question"}
    assert "evaluation_mode" in answer_rows[0]


def test_hard_hidden_generator_default_names_are_synthetic() -> None:
    source = Path("scripts/generate_hard_hidden_math.py").read_text(encoding="utf-8")
    assert "data/synthetic_hard_math.jsonl" in source
    assert "data/synthetic_hard_math_answers.jsonl" in source


def test_hard_hidden_large_profile_writes_min_proof_score(tmp_path: Path) -> None:
    questions = tmp_path / "hard300_questions.jsonl"
    answers = tmp_path / "hard300_answers.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/generate_hard_hidden_math.py",
            "--questions",
            str(questions),
            "--answers",
            str(answers),
            "--profile",
            "large",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "generated=360" in proc.stdout
    answer_rows = [
        json.loads(line) for line in answers.read_text(encoding="utf-8").splitlines()
    ]
    assert len(answer_rows) == 360
    proof_rows = [
        row for row in answer_rows if row["evaluation_mode"] == "proof_quality"
    ]
    assert len(proof_rows) == 120
    assert {row["min_proof_score"] for row in proof_rows} == {0.68}
