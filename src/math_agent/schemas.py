from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MathQuestion(BaseModel):
    question: str
    question_id: str = Field(default="unknown")


class ProblemParse(BaseModel):
    goal: str
    givens: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)


class ToolTrace(BaseModel):
    tool: Literal["python", "sympy", "none"]
    purpose: str
    status: Literal["success", "fail", "skipped"]
    summary: str


class FinalAnswer(BaseModel):
    type: Literal["number", "expression", "set", "proof", "algorithm", "text"]
    value: str
    boxed: str


class Verification(BaseModel):
    method: Literal[
        "symbolic_check", "numeric_check", "substitution", "logic_review", "self_review", "none"
    ]
    passed: bool
    notes: str


class SolveResult(BaseModel):
    question_id: str
    domain: str
    problem_type: str
    problem_parse: ProblemParse
    solution_plan: list[str] = Field(default_factory=list)
    visible_solution_steps: list[str] = Field(default_factory=list)
    tool_trace: list[ToolTrace] = Field(default_factory=list)
    final_answer: FinalAnswer
    verification: Verification
    didactic_hint: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["success", "partial", "fail"]
    error: str | None = None


# compatibility alias for older imports
MathResult = SolveResult


def make_failure_result(question_id: str, question: str, error_message: str) -> SolveResult:
    return SolveResult(
        question_id=question_id,
        domain="unknown",
        problem_type="unknown",
        problem_parse=ProblemParse(goal=question, givens=[], symbols=[]),
        solution_plan=[],
        visible_solution_steps=[],
        tool_trace=[
            ToolTrace(
                tool="none",
                purpose="skip_due_to_error",
                status="fail",
                summary=error_message,
            )
        ],
        final_answer=FinalAnswer(type="text", value="", boxed=""),
        verification=Verification(method="none", passed=False, notes="No verification due to failure."),
        didactic_hint="请先检查题目输入格式或稍后重试。",
        confidence=0.0,
        status="fail",
        error=error_message,
    )


def validate_result_dict(data: dict) -> SolveResult:
    return SolveResult.model_validate(data)
