from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from math_agent.submission.dry_run import build_dry_run_config, run_official_dry_run
from math_agent.submission.io import load_dry_run_questions, validate_dry_run_questions


def test_load_and_validate_questions(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps({"question_id": "q1", "question": "2+3"}),
                json.dumps({"id": "q2", "prompt": "x+x"}),
                "{bad-json}",
                json.dumps({"qid": "q4", "domain": "algebra"}),
            ]
        ),
        encoding="utf-8",
    )
    qs = load_dry_run_questions(input_path)
    assert [q.question_id for q in qs] == ["q1", "q2", "line-3", "q4"]
    stats = validate_dry_run_questions(qs)
    assert stats["total"] == 4
    assert stats["invalid"] == 2


def test_limit_effective(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        "\n".join(
            json.dumps({"question_id": f"q{i}", "question": "a"}) for i in range(5)
        ),
        encoding="utf-8",
    )
    qs = load_dry_run_questions(input_path, limit=2)
    assert len(qs) == 2


def test_dry_run_outputs_and_forbidden_name(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        json.dumps(
            {"question_id": "q1", "question": "计算 2+3", "answer_type": "number"}
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    cfg = build_dry_run_config(
        input_path=input_path, out_dir=out_dir, mock=True, save_trace=False
    )
    summary = run_official_dry_run(cfg, command="test")
    assert summary.total == 1
    assert (out_dir / "dry_run_results.jsonl").exists()
    assert (out_dir / "dry_run_summary.json").exists()
    assert (out_dir / "dry_run_report.md").exists()
    assert (out_dir / "run_record.json").exists()
    assert (out_dir / "config_snapshot.json").exists()
    assert not (out_dir / "official_results.jsonl").exists()
    report = (out_dir / "dry_run_report.md").read_text(encoding="utf-8")
    assert "This is NOT official evaluation." in report
    assert "official accuracy" in report

    try:
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            results_name="official_results.jsonl",
        )
    except ValueError as exc:
        assert "forbidden_official_results_name" in str(exc)
    else:
        raise AssertionError("expected forbidden results name to fail")


def test_real_requires_allow_real_guard(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q1", "question": "1+1"}), encoding="utf-8"
    )
    with subprocess.Popen(
        [
            sys.executable,
            "scripts/run_official_dry_run.py",
            "--input",
            str(input_path),
            "--out-dir",
            str(tmp_path / "o"),
            "--real",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as p:
        _, err = p.communicate()
        assert p.returncode != 0
        assert "real_run_requires_allow_real" in err


def test_cli_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/run_official_dry_run.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--input" in proc.stdout
