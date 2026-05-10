from __future__ import annotations

from .schemas import MathQuestion, MathResult


def _mock_solve_text(question: str) -> tuple[str, str, bool, str | None]:
    q = question.replace("=", "").replace("?", "").strip()
    try:
        answer = str(eval(q, {"__builtins__": {}}, {}))
        return answer, f"Mock evaluated expression: {q}", True, None
    except Exception as exc:
        return "", "Mock solver failed.", False, str(exc)


def solve_question(question: MathQuestion, mock: bool = True, model: str = "intern-s1") -> MathResult:
    if not mock:
        return MathResult(
            question_id=question.question_id,
            question=question.question,
            answer="",
            explanation="Real API mode disabled in this scaffold.",
            success=False,
            error="non-mock mode is not available",
            metadata={"mode": "disabled", "model": model},
        )

    answer, explanation, success, error = _mock_solve_text(question.question)
    return MathResult(
        question_id=question.question_id,
        question=question.question,
        answer=answer,
        explanation=explanation,
        success=success,
        error=error,
        metadata={"mode": "mock", "model": model},
    )
