import json
import subprocess
import sys

from math_agent.harness.formatter_repair import (
    detect_dirty_final_answer,
    proof_safe_finalize,
    repair_solve_result,
    sanitize_boxed,
)
from math_agent.schemas import FinalAnswer, ProblemParse, SolveResult, Verification


def _base_result() -> SolveResult:
    return SolveResult(
        question_id="q1",
        domain="algebra",
        problem_type="number",
        problem_parse=ProblemParse(goal="1+1", givens=[], symbols=[]),
        solution_plan=[],
        visible_solution_steps=["最终答案：2"],
        tool_trace=[],
        final_answer=FinalAnswer(type="number", value="2", boxed="\\boxed{2}"),
        verification=Verification(method="self_review", passed=True, notes="ok"),
        didactic_hint="",
        confidence=0.8,
        status="success",
        error=None,
    )


def test_missing_final_answer_repaired():
    repaired = repair_solve_result({"question_id": "x", "answer": "最终答案：7"})
    assert repaired.final_answer.value == "7"


def test_empty_final_value_repaired_from_steps():
    base = _base_result().model_dump()
    base["final_answer"]["value"] = ""
    base["visible_solution_steps"] = ["解得 x=3", "答案：3"]
    repaired = repair_solve_result(base)
    assert repaired.final_answer.value == "3"


def test_sanitize_boxed_long_markdown():
    assert sanitize_boxed("### 步骤一\n步骤二\n```python\n1\n```") == ""


def test_dirty_boxed_markdown_and_code_flags():
    base = _base_result().model_dump()
    base["final_answer"]["boxed"] = "```text\nproof\n```"
    flags = detect_dirty_final_answer(base)
    assert "dirty_boxed" in flags


def test_proof_empty_boxed_valid():
    base = _base_result().model_copy(update={"problem_type": "proof", "final_answer": FinalAnswer(type="proof", value="已证明：命题成立", boxed="")})
    repaired = proof_safe_finalize(base)
    assert repaired.final_answer.boxed == ""
    assert repaired.status in {"success", "partial"}


def test_proof_boxed_pollution_flagged():
    base = _base_result().model_dump()
    base["final_answer"] = {"type": "proof", "value": "已证明：成立", "boxed": "证明如下：步骤一，步骤二"}
    flags = detect_dirty_final_answer(base)
    assert "proof_boxed_pollution" in flags


def test_boxed_42_fallback_flagged():
    base = _base_result().model_dump()
    base["final_answer"]["boxed"] = "\\boxed{42}"
    flags = detect_dirty_final_answer(base)
    assert "boxed_42_fallback" in flags


def test_bad_dict_returns_legal_result():
    repaired = repair_solve_result({"x": object()})
    assert repaired.status == "fail"


def test_normal_number_not_modified():
    base = _base_result()
    repaired = repair_solve_result(base)
    assert repaired.final_answer.value == "2"


def test_normal_expression_not_modified():
    base = _base_result().model_copy(update={"final_answer": FinalAnswer(type="expression", value="x+1", boxed="\\boxed{x+1}")})
    repaired = repair_solve_result(base)
    assert repaired.final_answer.value == "x+1"


def test_repair_result_json_dumps():
    repaired = repair_solve_result({"question_id": "q", "answer": "Answer: 5"})
    json.dumps(repaired.model_dump(), ensure_ascii=False)


def test_cli_mock_solve_and_batch_still_work(tmp_path):
    solve_cmd = [sys.executable, "-m", "math_agent.cli", "solve", "--question", "1+1=?"]
    p1 = subprocess.run(solve_cmd, capture_output=True, text=True, check=True)
    assert json.loads(p1.stdout)["status"] in {"success", "partial", "fail"}

    in_file = tmp_path / "in.jsonl"
    in_file.write_text('{"question_id":"q1","question":"1+1=?"}\n{"question_id":"q2","question":"2+2=?"}\n', encoding="utf-8")
    out_file = tmp_path / "out.jsonl"
    batch_cmd = [sys.executable, "-m", "math_agent.cli", "batch", "--input", str(in_file), "--output", str(out_file)]
    subprocess.run(batch_cmd, capture_output=True, text=True, check=True)
    assert out_file.exists()
