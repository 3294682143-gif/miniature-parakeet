from __future__ import annotations

from .schemas import (
    FinalAnswer,
    MathQuestion,
    ProblemParse,
    SolveResult,
    ToolTrace,
    Verification,
    make_failure_result,
)


def _mock_eval(question: str) -> tuple[str, str]:
    q = question.replace("=", "").replace("?", "").strip()
    answer = str(eval(q, {"__builtins__": {}}, {}))
    return q, answer


def solve_question(question: MathQuestion, mock: bool = True, model: str = "intern-s1") -> SolveResult:
    if not mock:
        return make_failure_result(
            question_id=question.question_id,
            question=question.question,
            error_message=f"non-mock mode is not available (model={model})",
        )

    try:
        normalized, answer = _mock_eval(question.question)
    except Exception as exc:
        return make_failure_result(question.question_id, question.question, str(exc))

    return SolveResult(
        question_id=question.question_id,
        domain="arithmetic",
        problem_type="evaluation",
        problem_parse=ProblemParse(
            goal=f"Compute the value of: {question.question}",
            givens=[question.question],
            symbols=[s for s in ["+", "-", "*", "/"] if s in question.question],
        ),
        solution_plan=["Normalize expression", "Evaluate expression", "Return boxed answer"],
        visible_solution_steps=[f"规范化表达式: {normalized}", f"计算得到: {answer}"],
        tool_trace=[
            ToolTrace(tool="python", purpose="evaluate expression", status="success", summary="eval completed")
        ],
        final_answer=FinalAnswer(type="number", value=answer, boxed=answer),
        verification=Verification(method="self_review", passed=True, notes="Mock arithmetic evaluation succeeded."),
        didactic_hint="可通过先去掉等号和问号，再按运算优先级计算。",
        confidence=0.95,
        status="success",
        error=None,
    )
