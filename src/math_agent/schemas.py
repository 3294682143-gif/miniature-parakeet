from __future__ import annotations

import json
import re
from hashlib import sha256
from math import isfinite
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from .security import redact_sensitive_data

MAX_QUESTION_CHARS = 32_768
MAX_QUESTION_ID_CHARS = 128
EXECUTION_PROVENANCE_VERSION = "evoexternmath-solve-v1"
EXECUTION_PROFILE_VERSION = "execution-profile-v1"
EXECUTION_PROFILE_KEYS = frozenset(
    {
        "profile_version",
        "schema",
        "client_class",
        "mock",
        "model",
        "endpoint_sha256",
        "timeout",
        "max_retries",
        "enable_tools",
        "save_trace",
        "trace_dir_sha256",
        "run_mode",
        "max_refine_rounds",
        "prompt_version",
        "prompt_config_sha256",
        "hard_mode_policy",
    }
)


class MathQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    question_id: str = Field(default="unknown", max_length=MAX_QUESTION_ID_CHARS)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized

    @field_validator("question_id")
    @classmethod
    def normalize_question_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question_id must not be blank")
        return normalized


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
        "symbolic_check",
        "numeric_check",
        "substitution",
        "logic_review",
        "self_review",
        "none",
    ]
    passed: StrictBool
    notes: str


class SolveResult(BaseModel):
    question_id: str = Field(max_length=MAX_QUESTION_ID_CHARS)
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
    input_fingerprint: str = Field(default="", max_length=64)
    execution_fingerprint: str = Field(default="", max_length=64)

    @field_validator("question_id")
    @classmethod
    def normalize_question_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question_id must not be blank")
        return normalized

    @field_validator("input_fingerprint", "execution_fingerprint")
    @classmethod
    def validate_sha256_fingerprint(cls, value: str) -> str:
        if value and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("fingerprints must be lowercase SHA-256 digests")
        return value

    @model_validator(mode="after")
    def validate_success_contract(self) -> "SolveResult":
        if self.status == "success" and (
            self.verification.passed is not True
            or not self.final_answer.value.strip()
            or self.error is not None
        ):
            raise ValueError(
                "successful results require verification, a final value, and no error"
            )
        return self


def is_semantically_successful(result: SolveResult) -> bool:
    return (
        result.status == "success"
        and result.verification.passed is True
        and bool(result.final_answer.value.strip())
        and result.error is None
    )


def question_fingerprint(question: str) -> str:
    normalized = str(question).strip()
    return sha256(normalized.encode("utf-8", errors="strict")).hexdigest()


def execution_provenance_fingerprint(
    *, question: str, execution_profile: dict[str, Any]
) -> str:
    """Bind a result to both its normalized input and execution configuration."""

    execution_profile = validate_execution_profile(execution_profile)
    payload = {
        "version": EXECUTION_PROVENANCE_VERSION,
        "input_fingerprint": question_fingerprint(question),
        "execution_profile": execution_profile,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8", errors="strict")).hexdigest()


def validate_execution_profile(profile: object) -> dict[str, Any]:
    if not isinstance(profile, dict) or set(profile) != EXECUTION_PROFILE_KEYS:
        raise ValueError("execution profile has an invalid field set")
    if profile.get("profile_version") != EXECUTION_PROFILE_VERSION:
        raise ValueError("execution profile version is unsupported")
    if profile.get("schema") != "SolveResult/v2":
        raise ValueError("execution profile schema is unsupported")
    for key in ("mock", "enable_tools", "save_trace"):
        if type(profile.get(key)) is not bool:
            raise ValueError(f"execution profile {key} must be a boolean")
    for key in ("client_class", "model", "prompt_version"):
        value = profile.get(key)
        if not isinstance(value, str) or len(value) > 512:
            raise ValueError(f"execution profile {key} must be a bounded string")
    if not profile.get("client_class") or not profile.get("model"):
        raise ValueError("execution profile client and model are required")
    for key in ("endpoint_sha256", "trace_dir_sha256"):
        value = profile.get(key)
        if not isinstance(value, str) or (
            value and re.fullmatch(r"[0-9a-f]{64}", value) is None
        ):
            raise ValueError(f"execution profile {key} must be a SHA-256 digest")
    prompt_digest = profile.get("prompt_config_sha256")
    if (
        not isinstance(prompt_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", prompt_digest) is None
    ):
        raise ValueError("execution profile prompt digest is invalid")
    for key in ("timeout", "max_retries"):
        value = profile.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise ValueError(f"execution profile {key} must be a positive integer")
    max_refine_rounds = profile.get("max_refine_rounds")
    if (
        isinstance(max_refine_rounds, bool)
        or not isinstance(max_refine_rounds, int)
        or not 0 <= max_refine_rounds <= 3
    ):
        raise ValueError("execution profile max_refine_rounds is invalid")
    if profile.get("run_mode") not in {"full", "fast", "tool-first"}:
        raise ValueError("execution profile run_mode is invalid")
    if profile.get("hard_mode_policy") is not None and not isinstance(
        profile.get("hard_mode_policy"), dict
    ):
        raise ValueError("execution profile hard_mode_policy is invalid")
    if profile["mock"] is True and profile["endpoint_sha256"]:
        raise ValueError("mock execution profiles must not bind a real endpoint")
    if profile["save_trace"] is False and profile["trace_dir_sha256"]:
        raise ValueError("no-trace execution profiles must not bind a trace directory")
    canonical = json.loads(
        json.dumps(
            profile,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    if not isinstance(canonical, dict):
        raise ValueError("execution profile is not canonical JSON")
    return canonical


def is_valid_model_call_evidence(
    value: object, *, expected_model: object, require_nonempty: bool
) -> bool:
    if not isinstance(value, list) or (require_nonempty and not value):
        return False
    return all(
        isinstance(call, dict)
        and call.get("stage") in {"router", "planner", "solver", "verifier", "refiner"}
        and call.get("status") in {"ok", "error", "no_change"}
        and call.get("model") == expected_model
        and not isinstance(call.get("prompt_chars"), bool)
        and isinstance(call.get("prompt_chars"), int)
        and call.get("prompt_chars", -1) >= 0
        and not isinstance(call.get("response_chars"), bool)
        and isinstance(call.get("response_chars"), int)
        and call.get("response_chars", -1) >= 0
        for call in value
    )


def is_valid_trace_audit_evidence(
    trace: object,
    result: SolveResult,
    *,
    expected_real_mode: bool | None,
) -> bool:
    if not isinstance(trace, dict):
        return False
    execution_profile = trace.get("execution_profile")
    question = trace.get("question")
    metadata = trace.get("metadata")
    model_calls = trace.get("model_calls")
    tool_calls = trace.get("tool_calls")
    errors = trace.get("errors")
    started_at = trace.get("started_at")
    finished_at = trace.get("finished_at")
    latency_seconds = trace.get("latency_seconds")
    prompt_version = trace.get("prompt_version")
    route_info = trace.get("route_info")
    verifier_result = trace.get("verifier_result")
    if (
        not isinstance(execution_profile, dict)
        or not isinstance(question, str)
        or not isinstance(metadata, dict)
        or not isinstance(model_calls, list)
        or not isinstance(tool_calls, list)
        or not isinstance(errors, list)
        or any(not isinstance(error, str) for error in errors)
        or not isinstance(started_at, str)
        or not started_at
        or not isinstance(finished_at, str)
        or not finished_at
        or isinstance(latency_seconds, bool)
        or not isinstance(latency_seconds, (int, float))
        or not isfinite(float(latency_seconds))
        or float(latency_seconds) < 0.0
        or not isinstance(prompt_version, str)
        or not isinstance(route_info, dict)
        or not isinstance(verifier_result, dict)
    ):
        return False
    try:
        profile = validate_execution_profile(execution_profile)
        recomputed = execution_provenance_fingerprint(
            question=question,
            execution_profile=profile,
        )
        canonical_tool_calls = [
            ToolTrace.model_validate(call, strict=True).model_dump()
            for call in tool_calls
        ]
    except (TypeError, ValueError):
        return False
    if canonical_tool_calls != tool_calls:
        return False
    if canonical_tool_calls != [item.model_dump() for item in result.tool_trace]:
        return False
    is_success = result.status == "success"
    profile_is_real = profile.get("mock") is False
    if not is_valid_model_call_evidence(
        model_calls,
        expected_model=profile.get("model"),
        require_nonempty=bool(is_success and profile_is_real),
    ):
        return False
    model_calls_count = trace.get("model_calls_count")
    if (
        type(model_calls_count) is not int
        or model_calls_count < 0
        or model_calls_count != len(model_calls)
    ):
        return False
    if is_success and (
        errors or any(call.get("status") != "ok" for call in model_calls)
    ):
        return False
    if is_success and profile_is_real:
        if model_calls[-1].get("stage") != "verifier":
            return False
        if not any(call.get("stage") == "solver" for call in model_calls) and not any(
            call.status == "success" for call in result.tool_trace
        ):
            return False
    if expected_real_mode is not None and profile_is_real is not expected_real_mode:
        return False
    if profile_is_real:
        if (
            metadata.get("real_execution_requested") is not True
            or metadata.get("mock_evaluation_only") is True
            or metadata.get("mock_results_are_not_official") is True
        ):
            return False
    elif (
        metadata.get("mock_evaluation_only") is not True
        or metadata.get("mock_results_are_not_official") is not True
        or metadata.get("real_execution_requested") is True
    ):
        return False
    return bool(
        trace.get("question_id") == result.question_id
        and question_fingerprint(question) == result.input_fingerprint
        and trace.get("input_fingerprint") == result.input_fingerprint
        and trace.get("execution_fingerprint") == result.execution_fingerprint
        and recomputed == result.execution_fingerprint
        and trace.get("run_mode") == profile.get("run_mode")
        and prompt_version == profile.get("prompt_version")
        and route_info.get("domain") == result.domain
        and route_info.get("problem_type") == result.problem_type
        and verifier_result == result.verification.model_dump()
        and trace.get("final_result") == result.model_dump()
    )


# compatibility alias for older imports
MathResult = SolveResult


def sanitize_protocol_metadata(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_sensitive_data(data)
    return sanitized if isinstance(sanitized, dict) else {}


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
    model_config = ConfigDict(validate_assignment=True)

    candidate_id: str
    source: str
    answer_type: str = "text"
    final_answer_value: str = ""
    final_answer_boxed: str = ""
    final_answer_type: str = "text"
    normalized_answer: str = ""
    verifier_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    verification_method: str = "none"
    verification_passed: StrictBool = False
    selected: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


class WeightedVoteResult(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

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


def make_failure_result(
    question_id: str,
    question: str,
    error_message: str,
    *,
    execution_fingerprint: str = "",
) -> SolveResult:
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
        verification=Verification(
            method="none", passed=False, notes="No verification due to failure."
        ),
        didactic_hint="请先检查题目输入格式或稍后重试。",
        confidence=0.0,
        status="fail",
        error=error_message,
        input_fingerprint=question_fingerprint(question),
        execution_fingerprint=execution_fingerprint,
    )


def validate_result_dict(data: dict) -> SolveResult:
    return SolveResult.model_validate(data)
