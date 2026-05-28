from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_benchmark_suite_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/run_benchmark_suite.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--mode-pattern" in proc.stdout
    assert "--ab-limit" in proc.stdout


def test_benchmark_suite_mock_run(tmp_path: Path) -> None:
    questions = tmp_path / "questions.jsonl"
    answers = tmp_path / "answers.jsonl"
    out_dir = tmp_path / "bench"
    questions.write_text(
        '{"question_id":"q1","question":"Compute gcd(48, 18). Give the final answer only."}\n'
        '{"question_id":"q2","question":"A rectangle has length 4 and width 5. Compute its area. Give the final answer only."}\n',
        encoding="utf-8",
    )
    answers.write_text(
        '{"question_id":"q1","answer":"6","domain":"number_theory","problem_type":"gcd"}\n'
        '{"question_id":"q2","answer":"20","domain":"geometry","problem_type":"area"}\n',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/run_benchmark_suite.py",
            "--input",
            str(questions),
            "--answers",
            str(answers),
            "--out-dir",
            str(out_dir),
            "--limit",
            "2",
            "--enable-tools",
            "--mode-pattern",
            "tool-first,fast",
            "--ab-limit",
            "1",
            "--hard-mode-levels",
            "off",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    summary = json.loads(
        (out_dir / "benchmark_summary.json").read_text(encoding="utf-8")
    )
    assert "mixed" in summary["runs"]
    assert (out_dir / "mixed_official_like" / "evaluation_report.md").exists()
    assert (out_dir / "mixed_official_like" / "failure_replay_report.md").exists()
