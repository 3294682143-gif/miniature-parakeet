import json
import subprocess
import sys

from math_agent.agents.proof_guardian import (
    check_proof_structure,
    detect_proof_problem,
    proof_final_answer_policy,
)
from math_agent.agents.verifier import Verifier
from math_agent.control.hard_mode import build_hard_mode_policy
from math_agent.control.pipeline_hook import build_runtime_config
from math_agent.control.proof_guardian_hook import build_proof_guardian_runtime_plan
from math_agent.control.verifier_routing import build_verifier_routing_plan
from math_agent.harness.formatter_repair import repair_solve_result
from math_agent.pipeline import MathAgentPipeline
from math_agent.proof import (
    build_proof_guardian_decision,
    extract_proof_text,
    proof_guardian_decision_to_metadata,
    proof_score_to_metadata,
    score_proof_candidate,
)
from math_agent.schemas import FinalAnswer, ProblemParse, SolveResult, Verification


def _proof_result(value: str = "", boxed: str = "") -> SolveResult:
    return SolveResult(
        question_id="q1",
        domain="algebra",
        problem_type="proof",
        problem_parse=ProblemParse(goal="证明", givens=[], symbols=[]),
        solution_plan=[],
        visible_solution_steps=["设 a=b，因此命题成立，证毕"],
        tool_trace=[],
        final_answer=FinalAnswer(type="proof", value=value, boxed=boxed),
        verification=Verification(method="logic_review", passed=True, notes="ok"),
        didactic_hint="",
        confidence=0.7,
        status="success" if value.strip() else "partial",
        error=None,
    )


def test_detect_proof_problem_cases():
    assert detect_proof_problem("证明任意偶数的平方仍为偶数")
    assert detect_proof_problem("prove identity element is unique")
    assert detect_proof_problem("求值", {"domain": "topology"})
    assert not detect_proof_problem("计算 2+3")
    assert not detect_proof_problem("解方程 2x+5=13")


def test_check_proof_structure_samples():
    questions = [
        "证明任意偶数的平方仍为偶数",
        "证明任意群 G 中单位元唯一",
        "证明 A∩B 是 A 的子集",
        "证明实数轴 R 在通常拓扑下是连通空间",
        "证明数列 1/n 收敛，并求极限",
        "Show that every finite subgroup has identity element",
    ]
    steps = "设 n=2k，因此 n^2=4k^2=2(2k^2)，所以为偶数。命题成立，证毕"
    for q in questions:
        result = check_proof_structure(q, steps)
        assert result.method == "logic_review"


def test_proof_policy_empty_value_and_boxed_cleanup():
    result = _proof_result(value="", boxed="```证明如下...```")
    repaired = repair_solve_result(result)
    assert repaired.final_answer.type == "proof"
    assert repaired.final_answer.boxed == ""
    assert repaired.final_answer.value != ""


def test_proof_policy_value_short_conclusion():
    result = _proof_result(value="这是很长的证明" * 20, boxed="")
    fixed = proof_final_answer_policy(result)
    assert fixed.final_answer.value in {"命题成立", "已证"}


def test_pipeline_non_proof_not_using_guardian():
    pipeline = MathAgentPipeline(mock=True, save_trace=False)
    out = pipeline.solve("计算 2+3", "n1")
    assert out.final_answer.type != "proof"


def test_guardian_error_no_crash(monkeypatch):
    import math_agent.agents.verifier as verifier_mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(verifier_mod, "check_proof_structure", boom)
    v = verifier_mod.Verifier(
        client=type("C", (), {"chat": lambda *_: "{}"})(), mock=True
    )
    out = v.verify("证明A", "设A", "已证", {"problem_type": "proof"})
    assert out.method in {"self_review", "logic_review"}


def test_proof_structure_alone_cannot_pass_real_verification():
    verifier = Verifier(
        client=type("InvalidVerifierClient", (), {"chat": lambda *_: "not-json"})(),
        mock=False,
    )
    hollow_proof = "assume 1 = 0. therefore 1 = 0. " "thus the conclusion follows. qed."

    result = verifier.verify(
        "prove that 1 = 0.",
        hollow_proof,
        "the conclusion follows",
        {"problem_type": "proof"},
    )

    assert result.passed is False
    assert result.method == "self_review"
    assert "Verifier fallback" in result.notes


def test_proof_rubric_core():
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


def test_proof_rubric_accepts_theorem_substitution_chain():
    text = (
        "Use the binomial theorem: (a+b)^n=sum C(n,k)a^(n-k)b^k. "
        "Step 1: substitute a=1 and b=1. Step 2: simplify both sides. "
        "Therefore 2^n=sum C(n,k), so the claim is proved."
    )
    score = score_proof_candidate(text)
    assert score.proof_complete
    assert score.score >= 0.68


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
