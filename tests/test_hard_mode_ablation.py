from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from math_agent.evaluation.hard_mode_ablation import (
    build_ablation_config,
    render_hard_mode_ablation_report,
    run_hard_mode_ablation,
    write_hard_mode_ablation_outputs,
)


def test_ablation_defaults() -> None:
    cfg = build_ablation_config()
    assert cfg.levels == ["off", "light", "standard", "strict"]


def test_ablation_rejects_unsafe_levels_and_unsupported_non_mock() -> None:
    with pytest.raises(ValueError, match="level"):
        build_ablation_config(levels=["../escape"])
    with pytest.raises(ValueError, match="mock"):
        build_ablation_config(mock=False)


def test_zero_limit_runs_zero_cases_and_labels_policy_only_evidence(
    tmp_path: Path,
) -> None:
    report = run_hard_mode_ablation(
        build_ablation_config(out_dir=str(tmp_path), limit=0)
    )

    assert report.total_cases == 0
    assert report.comparison["outcome_comparison_valid"] is False
    assert report.comparison["execution_effect"] == "policy_metadata_only"


def test_run_ablation_and_outputs(tmp_path: Path) -> None:
    cfg = build_ablation_config(out_dir=str(tmp_path), include_debugger=True, limit=5)
    report = run_hard_mode_ablation(cfg)
    assert len(report.runs) == 4
    assert report.comparison["levels"][0].get("candidate_budget") is not None
    assert report.comparison["levels"][0].get("verifier_level") is not None
    assert "json_valid_rate" in report.comparison["levels"][0]
    strict = next(r for r in report.runs if r.level == "strict")
    assert strict.policy["shadow_eval_required"] is True
    assert strict.policy["debugger_required"] is True
    assert strict.debugger_summary is not None

    md = render_hard_mode_ablation_report(report)
    assert "NOT official evaluation" in md

    write_hard_mode_ablation_outputs(report, tmp_path)
    assert (tmp_path / "hard_mode_ablation_summary.json").is_file()
    assert (tmp_path / "hard_mode_ablation_report.md").is_file()
    assert not (tmp_path / "official_results.jsonl").exists()
    json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))


def test_level_error_isolated(monkeypatch, tmp_path: Path) -> None:
    import math_agent.evaluation.hard_mode_ablation as mod

    original = mod.run_single_level_ablation

    def bad(level, cases, out_dir, include_debugger):
        if level == "light":
            raise RuntimeError("boom")
        return original(level, cases, out_dir, include_debugger)

    monkeypatch.setattr(mod, "run_single_level_ablation", bad)
    cfg = build_ablation_config(out_dir=str(tmp_path))
    report = run_hard_mode_ablation(cfg)
    assert len(report.runs) == 4
    assert not any(
        "all levels passed" in recommendation
        for recommendation in report.recommendation
    )
    assert any("failed to execute" in item for item in report.recommendation)


def test_broken_exception_rendering_isolated_at_both_ablation_levels(
    monkeypatch, tmp_path: Path
) -> None:
    import math_agent.evaluation.hard_mode_ablation as mod

    class BrokenError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("broken conversion")

    monkeypatch.setattr(
        mod,
        "run_shadow_eval",
        lambda *args, **kwargs: (_ for _ in ()).throw(BrokenError()),
    )
    single = mod.run_single_level_ablation(
        level="off",
        cases=[],
        out_dir=tmp_path / "single",
        include_debugger=False,
    )
    assert "message unavailable" in single.summary["error"]

    monkeypatch.setattr(
        mod,
        "run_single_level_ablation",
        lambda *args, **kwargs: (_ for _ in ()).throw(BrokenError()),
    )
    report = run_hard_mode_ablation(build_ablation_config(out_dir=str(tmp_path)))
    assert all("message unavailable" in run.summary["error"] for run in report.runs)


def test_cli_help_and_run(tmp_path: Path) -> None:
    r = subprocess.run(
        [sys.executable, "scripts/run_hard_mode_ablation.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    run = subprocess.run(
        [
            sys.executable,
            "scripts/run_hard_mode_ablation.py",
            "--out-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0
    json.loads(run.stdout)
    assert "token" not in run.stdout.lower()
    assert "api key" not in run.stdout.lower()
