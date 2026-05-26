from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from math_agent.control.candidate_budget import build_candidate_budget_plan
from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.control.pipeline_hook import (
    build_runtime_config,
    runtime_config_to_metadata,
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "math_agent.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_runtime_config_none_disabled() -> None:
    cfg = build_runtime_config(None)
    assert cfg.enabled is False


def test_candidate_budget_preview_levels() -> None:
    assert (
        build_runtime_config(
            build_hard_mode_policy(True, "off")
        ).effective_candidate_budget
        == 1
    )
    assert (
        build_runtime_config(
            build_hard_mode_policy(True, "light")
        ).effective_candidate_budget
        == 2
    )
    assert (
        build_runtime_config(
            build_hard_mode_policy(True, "standard")
        ).effective_candidate_budget
        == 3
    )


def test_strict_budget_capped_and_notes() -> None:
    cfg = build_runtime_config(build_hard_mode_policy(True, "strict"))
    assert cfg.candidate_budget == 5
    assert cfg.effective_candidate_budget == 3
    assert "candidate_budget_capped_for_controlled_hook" in cfg.notes


def test_strict_no_trace_wins() -> None:
    cfg = build_runtime_config(build_hard_mode_policy(True, "strict"), no_trace=True)
    assert cfg.trace_allowed is False
    assert "trace_required_by_policy_but_no_trace_flag_wins" in cfg.notes


def test_proof_guardian_standard_proof_enabled() -> None:
    p = build_hard_mode_policy(True, "standard", answer_type="proof")
    cfg = build_runtime_config(p, answer_type="proof")
    assert cfg.proof_guardian is True


def test_runtime_metadata_jsonable_and_no_secrets() -> None:
    cfg = build_runtime_config(build_hard_mode_policy(True, "strict"), no_trace=True)
    metadata = runtime_config_to_metadata(cfg)
    dumped = json.dumps(metadata, ensure_ascii=False).lower()
    assert "token" not in dumped
    assert "api_key" not in dumped
    assert ".env" not in dumped


def test_cli_default_no_hard_mode_runtime() -> None:
    proc = _run_cli(
        "solve",
        "--question",
        "计算 2+3",
        "--enable-tools",
        "--mode",
        "fast",
        "--no-trace",
    )
    assert proc.returncode == 0
    assert "hard_mode_runtime" not in proc.stdout
    assert '"value":"5"' in proc.stdout or "\\boxed{5}" in proc.stdout


def test_cli_hard_mode_light_and_strict_metadata(tmp_path: Path) -> None:
    for level, expected in [("light", 2), ("strict", 3)]:
        qid = f"hook_{level}"
        tdir = tmp_path / level
        proc = _run_cli(
            "solve",
            "--question",
            "计算 2+3",
            "--question-id",
            qid,
            "--enable-tools",
            "--mode",
            "fast",
            "--trace-dir",
            str(tdir),
            "--hard-mode",
            "--hard-mode-level",
            level,
        )
        assert proc.returncode == 0
        payload = json.loads((tdir / f"{qid}.json").read_text(encoding="utf-8"))
        meta = payload.get("metadata", {})
        assert meta.get("hard_mode_effect") == "controlled_runtime_hook"
        assert meta.get("hard_mode_candidate_budget_preview") == expected
        if level == "strict":
            assert meta.get("hard_mode_policy", {}).get("candidate_budget") == 5


def test_cli_strict_no_trace_and_status_success(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"
    proc = _run_cli(
        "solve",
        "--question",
        "计算 2+3",
        "--question-id",
        "q_nt",
        "--enable-tools",
        "--mode",
        "fast",
        "--hard-mode",
        "--hard-mode-level",
        "strict",
        "--trace-dir",
        str(trace_dir),
        "--no-trace",
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "success"
    assert payload["final_answer"]["value"] == "5"
    assert not (trace_dir / "q_nt.json").exists()
    assert not Path("official_results.jsonl").exists()


def test_runtime_config_candidate_budget_plan_consistent() -> None:
    cfg = build_runtime_config(build_hard_mode_policy(True, "strict"))
    plan = build_candidate_budget_plan(cfg)
    assert plan.requested_budget == cfg.candidate_budget
    assert plan.effective_budget == cfg.effective_candidate_budget
