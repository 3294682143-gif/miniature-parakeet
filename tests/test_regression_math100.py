from __future__ import annotations

import json
import subprocess
import sys


def test_regression_math100_dataset_present_and_labeled() -> None:
    questions = [
        json.loads(line)
        for line in open("data/regression_math100.jsonl", encoding="utf-8")
        if line.strip()
    ]
    answers = [
        json.loads(line)
        for line in open("data/regression_math100_answers.jsonl", encoding="utf-8")
        if line.strip()
    ]
    assert len(questions) >= 300
    assert len(questions) == len(answers)
    assert all({"question_id", "question"} <= set(row) for row in questions)
    assert all(
        {"question_id", "answer", "domain", "problem_type"} <= set(row)
        for row in answers
    )
    assert len({row["domain"] for row in answers}) >= 6
    assert len({row["problem_type"] for row in answers}) >= 8
    assert {"proof", "number_theory", "geometry", "recurrence", "functions"} <= {
        row["domain"] for row in answers
    }


def test_regression_math300_alias_present() -> None:
    questions = [
        json.loads(line)
        for line in open("data/regression_math300.jsonl", encoding="utf-8")
        if line.strip()
    ]
    answers = [
        json.loads(line)
        for line in open("data/regression_math300_answers.jsonl", encoding="utf-8")
        if line.strip()
    ]
    assert len(questions) >= 300
    assert len(questions) == len(answers)


def test_generate_regression_math100_script(tmp_path) -> None:
    questions = tmp_path / "q.jsonl"
    answers = tmp_path / "a.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/generate_regression_math100.py",
            "--questions",
            str(questions),
            "--answers",
            str(answers),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "generated=" in proc.stdout
    assert questions.exists()
    assert answers.exists()
