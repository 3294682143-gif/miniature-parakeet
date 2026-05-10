from __future__ import annotations

import ast

from .schemas import (
    FinalAnswer,
    MathQuestion,
    ProblemParse,
    SolveResult,
    ToolTrace,
    Verification,
    make_failure_result,
)

_ALLOWED_BINARY_OPS: dict[type[ast.AST], callable] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_UNARY_OPS: dict[type[ast.AST], callable] = {
    ast.UAdd: lambda a: a,
    ast.USub: lambda a: -a,
}


def _eval_safe_math_expr(expr: str) -> float | int:
    tree = ast.parse(expr, mode="eval")

    def _eval_node(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY_OPS:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            return _ALLOWED_BINARY_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPS:
            operand = _eval_node(node.operand)
            return _ALLOWED_UNARY_OPS[type(node.op)](operand)
        raise ValueError("unsupported expression")

    return _eval_node(tree)


def _mock_eval(question: str) -> tuple[str, str]:
    normalized = question.replace("=", "").replace("?", "").replace("计算", "").strip()
    answer = str(_eval_safe_math_expr(normalized))
    return normalized, answer


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
            ToolTrace(tool="python", purpose="evaluate expression", status="success", summary="safe AST eval completed")
        ],
        final_answer=FinalAnswer(type="number", value=answer, boxed=answer),
        verification=Verification(method="self_review", passed=True, notes="Mock arithmetic evaluation succeeded."),
        didactic_hint="可通过先去掉等号和问号，再按运算优先级计算。",
        confidence=0.95,
        status="success",
        error=None,
    )
