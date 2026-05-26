import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "math_agent.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_contains_hard_mode_flags() -> None:
    proc = _run_cli("solve", "--help")
    assert proc.returncode == 0
    assert "--hard-mode" in proc.stdout
    assert "--hard-mode-level" in proc.stdout


def test_default_smoke_and_no_hard_mode_in_output() -> None:
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
    assert "traceback" not in proc.stdout.lower()
    assert "hard_mode_policy" not in proc.stdout
    assert "candidate_budget_plan" not in proc.stdout
    assert '"value":"5"' in proc.stdout or "\\boxed{5}" in proc.stdout


def test_hard_mode_smokes_and_trace_metadata(tmp_path: Path) -> None:
    for level in ["light", "standard", "strict"]:
        qid = f"q_{level}"
        trace_dir = tmp_path / level
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
            str(trace_dir),
            "--hard-mode",
            "--hard-mode-level",
            level,
        )
        assert proc.returncode == 0
        trace_file = trace_dir / f"{qid}.json"
        assert trace_file.exists()
        payload = json.loads(trace_file.read_text(encoding="utf-8"))
        meta = payload.get("metadata", {})
        assert meta.get("hard_mode_level") == level
        assert meta.get("hard_mode_effect") == "controlled_runtime_hook"
        assert "hard_mode_runtime" in meta
        if level == "strict":
            assert (
                meta.get("verifier_routing_plan", {}).get("route")
                == "strict_verifier_preview"
            )
        assert "--real" not in proc.args


def test_hard_mode_no_trace_no_official_results(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"
    proc = _run_cli(
        "solve",
        "--question",
        "计算 2+3",
        "--question-id",
        "q_no_trace",
        "--enable-tools",
        "--mode",
        "fast",
        "--trace-dir",
        str(trace_dir),
        "--no-trace",
        "--hard-mode",
        "--hard-mode-level",
        "strict",
    )
    assert proc.returncode == 0
    assert not (trace_dir / "q_no_trace.json").exists()
    assert not Path("official_results.jsonl").exists()


def test_invalid_hard_mode_level_rejected() -> None:
    proc = _run_cli(
        "solve", "--question", "1+1=?", "--hard-mode", "--hard-mode-level", "bad"
    )
    assert proc.returncode != 0


def test_hard_mode_strict_proof_trace_has_proof_guardian(tmp_path: Path) -> None:
    trace_dir = tmp_path / "proof"
    qid = "q_proof"
    proc = _run_cli(
        "solve",
        "--question",
        "证明偶数加偶数仍为偶数",
        "--question-id",
        qid,
        "--enable-tools",
        "--mode",
        "fast",
        "--trace-dir",
        str(trace_dir),
        "--hard-mode",
        "--hard-mode-level",
        "strict",
    )
    assert proc.returncode == 0
    payload = json.loads((trace_dir / f"{qid}.json").read_text(encoding="utf-8"))
    meta = payload.get("metadata", {})
    assert meta.get("proof_guardian_effect") == "preview_only"
    assert "proof_guardian_plan" in meta
