from math_agent.agents.proof_guardian import check_proof_structure, detect_proof_problem, proof_final_answer_policy
from math_agent.harness.formatter_repair import repair_solve_result
from math_agent.pipeline import MathAgentPipeline
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
        status="success",
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
    v = verifier_mod.Verifier(client=type("C", (), {"chat": lambda *_: "{}"})(), mock=True)
    out = v.verify("证明A", "设A", "已证", {"problem_type": "proof"})
    assert out.method in {"self_review", "logic_review"}
