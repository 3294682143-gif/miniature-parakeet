from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from math_agent.control.candidate_budget import (
    build_candidate_budget_plan,
    candidate_budget_plan_to_metadata,
)
from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.control.pipeline_hook import build_runtime_config
from math_agent.control.verifier_routing import (
    build_verifier_routing_plan,
    verifier_routing_plan_to_metadata,
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "math_agent.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _cfg(level: str, answer_type: str = "text"):
    return build_runtime_config(
        build_hard_mode_policy(True, level, answer_type=answer_type),
        answer_type=answer_type,
    )


def test_candidate_budget_plan_levels_and_metadata_jsonable() -> None:
    disabled = build_candidate_budget_plan(None)
    assert disabled.enabled is False
    assert disabled.effective_budget == 1

    light = build_candidate_budget_plan(_cfg("light"))
    assert light.effective_budget == 2

    standard = build_candidate_budget_plan(_cfg("standard"))
    assert standard.effective_budget == 3

    strict = build_candidate_budget_plan(_cfg("strict"))
    assert strict.requested_budget == 3  # effective_candidate_budget from runtime_config, capped at max_budget
    assert strict.effective_budget == 3
    assert strict.strategy == "capped_budget_preview"

    dumped = json.dumps(
        candidate_budget_plan_to_metadata(strict), ensure_ascii=False
    ).lower()
    assert "token" not in dumped
    assert "api_key" not in dumped
    assert ".env" not in dumped


def test_verifier_routing_plan_levels_and_metadata_jsonable() -> None:
    disabled = build_verifier_routing_plan(None)
    assert disabled.route == "default"

    basic = build_verifier_routing_plan(_cfg("light"))
    assert basic.route == "basic_verifier"

    strong = build_verifier_routing_plan(_cfg("standard"))
    assert strong.route == "strong_verifier_preview"

    strict = build_verifier_routing_plan(_cfg("strict"))
    assert strict.route == "strict_verifier_preview"
    assert "strict_verifier_preview_only" in strict.notes

    proof = build_verifier_routing_plan(_cfg("standard", "proof"), answer_type="proof")
    assert proof.proof_guardian is True

    dumped = json.dumps(
        verifier_routing_plan_to_metadata(strict), ensure_ascii=False
    ).lower()
    assert "token" not in dumped
    assert "api_key" not in dumped
    assert ".env" not in dumped


def test_cli_candidate_verifier_preview_and_default_unchanged(tmp_path: Path) -> None:
    default_proc = _run_cli(
        "solve",
        "--question",
        "计算 2+3",
        "--enable-tools",
        "--mode",
        "fast",
        "--no-trace",
    )
    assert default_proc.returncode == 0
    assert '"value":"5"' in default_proc.stdout
    assert "candidate_budget_plan" not in default_proc.stdout

    light_qid = "p14_light"
    light_dir = tmp_path / "light"
    light_proc = _run_cli(
        "solve",
        "--question",
        "计算 2+3",
        "--question-id",
        light_qid,
        "--enable-tools",
        "--mode",
        "fast",
        "--trace-dir",
        str(light_dir),
        "--hard-mode",
        "--hard-mode-level",
        "light",
    )
    assert light_proc.returncode == 0
    light_trace = json.loads(
        (light_dir / f"{light_qid}.json").read_text(encoding="utf-8")
    )
    light_meta = light_trace.get("metadata", {})
    assert light_meta.get("candidate_budget_plan", {}).get("effective_budget") == 2

    strict_qid = "p14_strict"
    strict_dir = tmp_path / "strict"
    strict_proc = _run_cli(
        "solve",
        "--question",
        "计算 2+3",
        "--question-id",
        strict_qid,
        "--enable-tools",
        "--mode",
        "fast",
        "--trace-dir",
        str(strict_dir),
        "--hard-mode",
        "--hard-mode-level",
        "strict",
    )
    assert strict_proc.returncode == 0
    strict_trace = json.loads(
        (strict_dir / f"{strict_qid}.json").read_text(encoding="utf-8")
    )
    strict_meta = strict_trace.get("metadata", {})
    assert (
        strict_meta.get("verifier_routing_plan", {}).get("route")
        == "strict_verifier_preview"
    )
    assert strict_trace["final_result"]["final_answer"]["value"] == "5"
    assert strict_trace["final_result"]["status"] == "success"
    assert not Path("official_results.jsonl").exists()
