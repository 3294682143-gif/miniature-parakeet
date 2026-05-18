from __future__ import annotations

from typing import Any, Literal

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


class CandidateAnswer(BaseModel):
    candidate_id: str
    source: str
    answer_type: Literal["number", "expression", "set", "proof", "algorithm", "text"] = "text"
    final_answer_value: str = ""
    final_answer_boxed: str = ""
    normalized_answer: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    verifier_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    verification_method: str = "none"
    verification_passed: bool = False


class WeightedVoteResult(BaseModel):
    selected_candidate_id: str | None
    selected_answer: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    need_more_verification: bool = True
    issues: list[str] = Field(default_factory=list)
    cluster_summary: list[dict] = Field(default_factory=list)


# compatibility alias for older imports
MathResult = SolveResult


_SENSITIVE_KEYWORDS = ("api_key", "authorization", "bearer", "token", "secret", "password", ".env")


def sanitize_protocol_metadata(data: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        lower_key = key_text.lower()
        if any(k in lower_key for k in _SENSITIVE_KEYWORDS):
            sanitized[key_text] = "[REDACTED]"
            continue
        if isinstance(value, dict):
            sanitized[key_text] = sanitize_protocol_metadata(value)
            continue
        if isinstance(value, list):
            sanitized_list: list[Any] = []
            for item in value:
                if isinstance(item, dict):
                    sanitized_list.append(sanitize_protocol_metadata(item))
                elif isinstance(item, str) and "bearer " in item.lower():
                    sanitized_list.append("[REDACTED]")
                else:
                    sanitized_list.append(item)
            sanitized[key_text] = sanitized_list
            continue
        if isinstance(value, str) and "bearer " in value.lower():
            sanitized[key_text] = "[REDACTED]"
            continue
        sanitized[key_text] = value
    return sanitized


def to_jsonable(model: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        return model.model_dump()
    return sanitize_protocol_metadata(model)


class AgentStep(BaseModel):
    step_id: str
    agent_name: str
    role: str
    input_summary: str = ""
    output_summary: str = ""
    status: Literal["success", "partial", "fail", "skipped"]
    risk_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


class ToolCallRecord(BaseModel):
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    status: Literal["success", "fail", "skipped"]
    latency_seconds: float | None = None
    error: str | None = None

    def model_post_init(self, __context: Any) -> None:
        self.parameters = sanitize_protocol_metadata(self.parameters)


class ProtocolVerifierResult(BaseModel):
    passed: bool
    method: Literal[
        "symbolic",
        "numeric",
        "substitution",
        "logic_review",
        "format_check",
        "weighted_vote",
        "self_review",
        "none",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    suggested_action: Literal["stop", "refine", "fallback", "fail"]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


class CandidateAnswer(BaseModel):
    candidate_id: str
    source: str
    final_answer_value: str = ""
    final_answer_type: str = "text"
    normalized_answer: str = ""
    verifier_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    selected: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


class WeightedVoteResult(BaseModel):
    selected_candidate_id: str | None = None
    selected_answer: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cluster_summary: list[dict[str, Any]] = Field(default_factory=list)
    need_more_verification: bool = False
    issues: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


def make_agent_step(**kwargs: Any) -> AgentStep:
    return AgentStep(**kwargs)


def make_tool_call_record(**kwargs: Any) -> ToolCallRecord:
    return ToolCallRecord(**kwargs)


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
