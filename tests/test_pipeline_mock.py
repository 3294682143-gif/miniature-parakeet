from hashlib import sha256
from pathlib import Path

import pytest

from math_agent.pipeline import (
    MathAgentPipeline,
    _crt_two,
    _eval_safe_math_expr,
    _extract_final_answer_non_proof,
    _extract_proof_conclusion,
    _proof_fallback_review,
    _run_tool_assist,
    extract_boxed_answer,
)
from math_agent.schemas import SolveResult, ToolTrace, Verification


def test_extract_boxed_answer():
    assert extract_boxed_answer("过程... \\boxed{42}") == "42"


def test_pipeline_mock_success_and_schema():
    result = MathAgentPipeline(mock=True).solve("1+1=?", "q1")
    assert isinstance(result, SolveResult)
    assert result.status == "success"


def test_pipeline_prompt_profile_hashes_the_same_immutable_snapshot(
    tmp_path: Path,
) -> None:
    original = Path("configs/prompts.yaml").read_bytes()
    prompt_path = tmp_path / "prompts.yaml"
    prompt_path.write_bytes(original)
    pipeline = MathAgentPipeline(
        mock=True,
        save_trace=False,
        prompt_config_path=prompt_path,
    )
    old_digest = sha256(original).hexdigest()
    prompt_path.write_bytes(original + b"\n# changed after construction\n")
    new_digest = sha256(prompt_path.read_bytes()).hexdigest()

    profile = pipeline.execution_profile()
    result = pipeline.solve("2+3", "prompt-snapshot")

    assert old_digest != new_digest
    assert profile["prompt_config_sha256"] == old_digest
    assert result.execution_fingerprint == pipeline.execution_fingerprint("2+3")
    assert pipeline.planner_agent.prompts == pipeline.solver_agent.prompts
    assert pipeline.planner_agent.prompts == pipeline.verifier_agent.prompts
    with pytest.raises(TypeError):
        pipeline.solver_agent.prompts["solver_system"] = "mutated"


def test_pipeline_arithmetic_and_tool_helpers_enforce_resource_limits():
    with pytest.raises(ValueError):
        _eval_safe_math_expr("9**1000000000")
    with pytest.raises(ValueError):
        _eval_safe_math_expr("+".join("1" for _ in range(300)))

    value = _crt_two(2, 1_000_000_007, 3, 1_000_000_009)
    assert value is not None
    assert value % 1_000_000_007 == 2
    assert value % 1_000_000_009 == 3

    answer, verification, trace = _run_tool_assist(
        "Euler phi(999999999999999999)", "number_theory", "program"
    )
    assert answer is None
    assert verification is None
    assert trace.status == "fail"

    answer, verification, trace = _run_tool_assist(
        "Given gcd(2,4)=2, calculate 10+1.", "calculation", "program"
    )
    assert answer is None
    assert verification is None
    assert trace.status == "skipped"


def test_proof_fallback_never_overrides_explicit_verifier_rejection():
    rejected = Verification(
        method="logic_review",
        passed=False,
        notes="logical contradiction detected",
    )
    keyword_spam = (
        "assume therefore proof conclusion qed "
        "assume therefore proof conclusion qed "
        "assume therefore proof conclusion qed"
    )

    reviewed = _proof_fallback_review(
        keyword_spam,
        {"problem_type": "proof"},
        rejected,
        "proof",
        "Proved: claim",
        "",
    )

    assert reviewed is rejected


def test_proof_fallback_never_upgrades_non_json_verifier_failure():
    rejected = Verification(
        method="self_review",
        passed=False,
        notes="Verifier fallback: non-JSON or invalid JSON response.",
    )
    false_proof = (
        "Let x=1. Since x=1, therefore x=2. This proves the theorem. "
        "Let x=1 again; since the premise is repeated, therefore the false "
        "conclusion follows."
    )

    reviewed = _proof_fallback_review(
        false_proof,
        {"problem_type": "proof"},
        rejected,
        "proof",
        "Proved: x=2",
        "",
    )

    assert reviewed is rejected
    assert reviewed.passed is False


def test_pipeline_calls_all_agents(monkeypatch):
    calls = []

    class DummyRoute:
        domain = "Arithmetic"
        problem_type = "calculation"
        reason = "ok"
        confidence = 0.8

    monkeypatch.setattr(
        "math_agent.pipeline.router.Router.route",
        lambda self, q: calls.append("route") or DummyRoute(),
    )
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan",
        lambda self, q, r: calls.append("plan") or {"k": "v"},
    )
    monkeypatch.setattr(
        "math_agent.pipeline.solver.Solver.solve",
        lambda self, q, r, p: calls.append("solve") or "\\boxed{2}",
    )
    monkeypatch.setattr(
        "math_agent.pipeline.verifier.Verifier.verify",
        lambda self, q, d, f, r=None: calls.append("verify")
        or Verification(method="self_review", passed=True, notes="pass"),
    )
    monkeypatch.setattr(
        "math_agent.pipeline.explainer.run", lambda q: calls.append("explain") or "hint"
    )
    result = MathAgentPipeline(mock=True).solve("1+1=?", "q2")
    assert result.final_answer.boxed == "\\boxed{2}"
    assert calls == ["route", "plan", "solve", "verify", "explain"]


def test_refiner_called_when_verifier_fails(monkeypatch):
    state = {"verify": 0, "refine": 0}

    class DummyRoute:
        domain = "Arithmetic"
        problem_type = "calculation"
        reason = "ok"
        confidence = 0.8

    monkeypatch.setattr(
        "math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute()
    )
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan", lambda self, q, r: {"k": "v"}
    )
    monkeypatch.setattr(
        "math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: "answer: 1"
    )

    def fake_verify(self, q, d, f, r=None):
        state["verify"] += 1
        return Verification(method="self_review", passed=state["verify"] > 1, notes="x")

    monkeypatch.setattr("math_agent.pipeline.verifier.Verifier.verify", fake_verify)
    monkeypatch.setattr(
        "math_agent.pipeline.refiner.Refiner.refine",
        lambda self, q, draft, feedback: state.__setitem__(
            "refine", state["refine"] + 1
        )
        or "\\boxed{2}",
    )
    out = MathAgentPipeline(mock=False, max_refine_rounds=1).solve("1+1=?", "q3")
    assert state["refine"] == 1
    assert out.verification.passed is True


@pytest.mark.parametrize("value", [-1, 4, 10**12, True, 1.5, float("inf")])
def test_pipeline_rejects_unbounded_refine_rounds(value) -> None:
    with pytest.raises(ValueError, match="max_refine_rounds"):
        MathAgentPipeline(max_refine_rounds=value)


def test_failed_tool_diagnostic_cannot_be_upgraded(monkeypatch) -> None:
    monkeypatch.setattr(
        "math_agent.pipeline._run_tool_assist",
        lambda *args, **kwargs: (
            "999",
            Verification(method="numeric_check", passed=False, notes="failed"),
            ToolTrace(tool="sympy", purpose="test", status="fail", summary="failed"),
        ),
    )
    pipeline = MathAgentPipeline(mock=False, enable_tools=True, max_refine_rounds=0)
    monkeypatch.setattr(
        pipeline.verifier_agent,
        "verify",
        lambda *args, **kwargs: Verification(
            method="self_review", passed=True, notes="independent"
        ),
    )

    result = pipeline.solve("What is 2+2?", "failed-tool")

    assert result.final_answer.value != "999"


@pytest.mark.parametrize(
    "question",
    [
        "Compute gcd(8,12) and gcd(9,15)",
        "Compute 12 choose 2 and 10 choose 3",
        "Compute Euler phi of 12 and Euler phi of 15",
        "Find the remainder when 7 is divided by 5 and the remainder when 8 is divided by 3",
    ],
)
def test_repeated_tool_targets_are_not_marked_as_single_answer(question: str) -> None:
    answer, verification, trace = _run_tool_assist(question, "calculation", "program")

    assert answer is None
    assert verification is None
    assert trace.status == "skipped"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compute 2+3", "5"),
        ("Calculate 2+3", "5"),
        ("What is 2+3?", "5"),
        ("Solve 2x+5=13", "x=4"),
        ("solve x+1=3", "x=2"),
        ("Solve the equation 2*x+5=13", "x=4"),
        ("Compute log base 2.9 of 8.41", "2"),
    ],
)
def test_common_english_tool_requests_are_parsed_without_command_words(
    question: str, expected: str
) -> None:
    answer, verification, trace = _run_tool_assist(question, "calculation", "program")

    assert answer is not None and expected in answer
    assert verification is not None and verification.passed is True
    assert trace.status == "success"


@pytest.mark.parametrize(
    "question",
    [
        "Find the slope of the line through (1,2) and (1,5)",
        "Find the y-intercept of y=1/x",
        "A right triangle has legs 0 and 5. Compute its inradius",
        "Compute log base 1 of 2",
    ],
)
def test_undefined_or_degenerate_tool_results_never_pass(question: str) -> None:
    _, verification, trace = _run_tool_assist(question, "calculation", "program")

    assert verification is None or verification.passed is False
    assert trace.status != "success"


@pytest.mark.parametrize(
    "question",
    [
        "Find the slope of the line through (1,2) and (1,5)",
        "Find the y-intercept of y=1/x",
        "A right triangle has legs 0 and 5. Compute its inradius",
        "Compute log base 1 of 2",
        "Compute gcd(8,12) and gcd(9,15)",
        "Prove that 1=0.",
    ],
)
def test_mock_pipeline_never_certifies_unchecked_or_undefined_answers(
    question: str,
) -> None:
    result = MathAgentPipeline(
        mock=True, enable_tools=True, run_mode="tool-first", max_refine_rounds=0
    ).solve(question, "mock-unchecked")

    assert result.status != "success"
    assert result.verification.passed is False


def test_non_proof_prefers_boxed_and_not_long_markdown(monkeypatch):
    class DummyRoute:
        domain = "Optimization"
        problem_type = "calculation"
        recommended_solver = "optimization"
        reason = "ok"
        confidence = 0.9

    long_draft = "### 问题解析\n很多解释\n\n继续解释\n最终得到 \\boxed{\\dfrac{1}{4}}"
    monkeypatch.setattr(
        "math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute()
    )
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan",
        lambda self, q, r: {"problem_parse": {}, "solution_plan": []},
    )
    monkeypatch.setattr(
        "math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: long_draft
    )
    monkeypatch.setattr(
        "math_agent.pipeline.verifier.Verifier.verify",
        lambda self, q, d, f, r=None: Verification(
            method="self_review", passed=True, notes="pass"
        ),
    )
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: "hint")

    out = MathAgentPipeline(mock=False).solve("opt", "smoke_005")
    assert out.final_answer.type in {"number", "expression"}
    assert out.final_answer.value in {r"\dfrac{1}{4}", "1/4"}
    assert out.final_answer.boxed in {r"\boxed{\dfrac{1}{4}}", r"\boxed{1/4}"}
    assert len(out.final_answer.boxed) <= 120
    assert "###" not in out.final_answer.boxed
    assert out.status in {"success", "partial"}


def test_non_proof_extracts_multiple_final_boxed_values():
    draft = r"Work... Final Answer: \boxed{2} and \boxed{3}"
    assert _extract_final_answer_non_proof(draft, draft) == "[2,3]"


def test_proof_conclusion_empty_shell_falls_back():
    assert _extract_proof_conclusion("结论：**") == "命题已完成证明。"


def test_proof_conclusion_extracts_clean_statement():
    text = "设x属于A∩B。\n因此 A∩B 是 A 的子集\n证毕"
    assert _extract_proof_conclusion(text) == "已证明：A∩B 是 A 的子集"


def test_proof_conclusion_header_then_next_line_content():
    text = "**结论：**\n若 ||x_n-x|| -> 0，则 x_n 收敛到 x。"
    assert (
        _extract_proof_conclusion(text) == "已证明：若 ||x_n-x|| -> 0，则 x_n 收敛到 x"
    )


def test_proof_long_text_non_json_verifier_stays_partial(monkeypatch):
    class DummyRoute:
        domain = "SetLogic"
        problem_type = "proof"
        recommended_solver = "proof"
        reason = "ok"
        confidence = 0.9

    long_proof = "证明：根据定义，设x∈A∩B，则x∈A且x∈B，因此x∈A，所以得结论。收敛" * 4
    monkeypatch.setattr(
        "math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute()
    )
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan",
        lambda self, q, r: {"problem_parse": {}, "solution_plan": []},
    )
    monkeypatch.setattr(
        "math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: long_proof
    )
    monkeypatch.setattr(
        "math_agent.pipeline.verifier.Verifier.verify",
        lambda self, q, d, f, r=None: Verification(
            method="self_review",
            passed=False,
            notes="Verifier fallback: non-JSON or invalid JSON response.",
        ),
    )
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: "hint")

    out = MathAgentPipeline(mock=False).solve("证明A∩B是A的子集", "proof_ok")
    assert out.status == "partial"
    assert out.verification.passed is False
    assert out.verification.method == "self_review"
    assert out.verification.notes.startswith("Verifier fallback: non-JSON")


def test_proof_short_hollow_text_stays_partial(monkeypatch):
    class DummyRoute:
        domain = "NumberTheory"
        problem_type = "proof"
        recommended_solver = "proof"
        reason = "ok"
        confidence = 0.7

    monkeypatch.setattr(
        "math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute()
    )
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan",
        lambda self, q, r: {"problem_parse": {}, "solution_plan": []},
    )
    monkeypatch.setattr(
        "math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: "证明：显然。"
    )
    monkeypatch.setattr(
        "math_agent.pipeline.verifier.Verifier.verify",
        lambda self, q, d, f, r=None: Verification(
            method="self_review",
            passed=False,
            notes="Verifier fallback: non-JSON or invalid JSON response.",
        ),
    )
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: "hint")

    out = MathAgentPipeline(mock=False).solve("证明命题", "proof_short")
    assert out.status == "partial"
    assert out.verification.passed is False


def test_proof_pre009_style_non_json_verifier_stays_partial(monkeypatch):
    class DummyRoute:
        domain = "NumberTheory"
        problem_type = "proof"
        recommended_solver = "proof"
        reason = "ok"
        confidence = 0.8

    proof_text = (
        "证明：若 n 是奇数，则 n^2 也是奇数。\n"
        "根据奇数的定义，存在整数 k，使得 n = 2k + 1。\n"
        "于是 n^2 = (2k+1)^2 = 2(2k^2 + 2k) + 1。\n"
        "因此 n^2 仍可写为 2m+1 的形式，符合奇数的定义。\n"
        "证明完成。"
    )
    monkeypatch.setattr(
        "math_agent.pipeline.router.Router.route", lambda self, q: DummyRoute()
    )
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan",
        lambda self, q, r: {"problem_parse": {}, "solution_plan": []},
    )
    monkeypatch.setattr(
        "math_agent.pipeline.solver.Solver.solve", lambda self, q, r, p: proof_text
    )
    monkeypatch.setattr(
        "math_agent.pipeline.verifier.Verifier.verify",
        lambda self, q, d, f, r=None: Verification(
            method="self_review",
            passed=False,
            notes="Verifier fallback: non-JSON or invalid JSON response.",
        ),
    )
    monkeypatch.setattr("math_agent.pipeline.explainer.run", lambda q: "hint")

    out = MathAgentPipeline(mock=False).solve(
        "证明若 n 是奇数，则 n^2 也是奇数。", "pre_009_number_theory"
    )
    assert out.status == "partial"
    assert out.final_answer.type == "proof"
    assert out.final_answer.boxed == ""
    assert out.verification.passed is False
    assert out.verification.method == "self_review"
    assert out.verification.notes.startswith("Verifier fallback: non-JSON")
