import json
import subprocess
import sys

from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.control.pipeline_hook import build_runtime_config
from math_agent.control.proof_guardian_hook import build_proof_guardian_runtime_plan
from math_agent.control.verifier_routing import build_verifier_routing_plan
from math_agent.proof import (
    build_proof_guardian_decision,
    extract_proof_text,
    proof_guardian_decision_to_metadata,
    proof_score_to_metadata,
    score_proof_candidate,
)


def test_proof_core():
    assert extract_proof_text("证明：abc") == "证明：abc"
    assert extract_proof_text({"final_answer_value": "设 x"}) == "设 x"
    empty = score_proof_candidate("")
    assert empty.proof_invalid and empty.score <= 0.2
    partial = score_proof_candidate("偶数加偶数仍是偶数，这是结论陈述")
    assert partial.proof_partial
    complete = score_proof_candidate(
        "设a,b为偶数，因为a=2m,b=2n，所以a+b=2(m+n)，故结论成立"
    )
    assert complete.proof_complete
    invalid = score_proof_candidate("存在矛盾 contradiction")
    assert "proof_contradiction_risk" in invalid.risk_flags
    assert json.dumps(proof_score_to_metadata(complete))


def test_decision_and_runtime():
    complete = score_proof_candidate("设a，因为a=2m，所以成立，故命题成立")
    d = build_proof_guardian_decision([complete])
    assert d.allow_finalization
    partial = score_proof_candidate("结论成立")
    d2 = build_proof_guardian_decision([partial], allow_partial=False)
    assert d2.requires_repair
    invalid = score_proof_candidate("矛盾 contradiction")
    d3 = build_proof_guardian_decision([invalid])
    assert not d3.allow_finalization
    assert json.dumps(proof_guardian_decision_to_metadata(d3))
    disabled = build_proof_guardian_runtime_plan(None, None, "", answer_type="proof")
    assert not disabled.enabled
    runtime = build_runtime_config(
        build_hard_mode_policy(enabled=True, level="strict", answer_type="proof"),
        no_trace=True,
        answer_type="proof",
    )
    route = build_verifier_routing_plan(runtime, answer_type="proof")
    plan = build_proof_guardian_runtime_plan(
        runtime, route, "设a，因为...所以...故...", answer_type="proof"
    )
    assert plan.enabled


def test_cli_and_demo(tmp_path):
    p = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "solve",
            "--question",
            "证明偶数加偶数仍为偶数",
            "--enable-tools",
            "--mode",
            "fast",
            "--hard-mode",
            "--hard-mode-level",
            "strict",
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "status" in p.stdout
    p2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "solve",
            "--question",
            "计算 2+3",
            "--enable-tools",
            "--mode",
            "fast",
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "proof_guardian_plan" not in p2.stdout
    out = tmp_path / "demo"
    subprocess.run(
        [sys.executable, "scripts/run_proof_guardian_demo.py", "--out-dir", str(out)],
        check=True,
    )
    assert (out / "proof_guardian_demo.json").exists()
