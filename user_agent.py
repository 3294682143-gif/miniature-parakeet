from __future__ import annotations

import inspect
import math
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
_SRC_ROOT_KEY = os.path.normcase(os.path.abspath(str(SRC_ROOT)))
sys.path[:] = [
    entry
    for entry in sys.path
    if os.path.normcase(os.path.abspath(entry or os.curdir)) != _SRC_ROOT_KEY
]
sys.path.insert(0, str(SRC_ROOT))

import math_agent.clients.interns1_client as _client_module  # noqa: E402
import math_agent.pipeline as _pipeline_module  # noqa: E402
import math_agent.schemas as _schemas_module  # noqa: E402
import math_agent.security as _security_module  # noqa: E402
from math_agent.clients.interns1_client import (  # noqa: E402
    MAX_MESSAGES,
    MAX_REQUEST_CHARS,
    MAX_RESPONSE_BYTES,
    MAX_TOKENS,
    InternS1Client,
)
from math_agent.pipeline import MathAgentPipeline  # noqa: E402
from math_agent.schemas import (  # noqa: E402
    MathQuestion,
    SolveResult,
    is_semantically_successful,
    sanitize_protocol_metadata,
)
from math_agent.security import safe_exception_text  # noqa: E402

for _module in (
    _client_module,
    _pipeline_module,
    _schemas_module,
    _security_module,
):
    if not Path(_module.__file__).resolve().is_relative_to(SRC_ROOT.resolve()):
        raise ImportError("user_agent dependency was not loaded from this checkout")


class _OfficialClientAdapter:
    """Normalize the official competition client to the local ChatClient shape."""

    def __init__(
        self,
        client: Any,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> None:
        self._client = client
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def model(self) -> str:
        return str(getattr(self._client, "model", "official-client"))

    def chat(
        self,
        messages: list[dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        if (
            not isinstance(messages, list)
            or not 1 <= len(messages) <= MAX_MESSAGES
            or any(
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message.get("role") not in {"assistant", "system", "user"}
                or not isinstance(message.get("content"), str)
                for message in messages
            )
        ):
            raise ValueError("invalid_request: messages do not match the safe schema")
        kwargs.setdefault("temperature", self.temperature)
        kwargs.setdefault("max_tokens", self.max_tokens)
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or not 0 <= float(temperature) <= 2
            or isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= MAX_TOKENS
        ):
            raise ValueError("invalid_request: sampling values are outside safe ranges")
        request_bytes = len(
            __import__("json").dumps(messages, ensure_ascii=True).encode("utf-8")
        )
        if request_bytes > MAX_REQUEST_CHARS:
            raise ValueError("invalid_request: messages exceed the size limit")
        chat_fn = self._client.chat
        if _accepts_positional_messages(chat_fn):
            response = chat_fn(messages, *args, **kwargs)
        else:
            response = chat_fn(*args, messages=messages, **kwargs)
        content = _extract_chat_content(response)
        if len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("invalid_response: response exceeds the size limit")
        return content


def _accepts_positional_messages(chat_fn: Any) -> bool:
    try:
        signature = inspect.signature(chat_fn)
    except (TypeError, ValueError):
        return True
    parameters = list(signature.parameters.values())
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in parameters):
        return True
    messages_param = signature.parameters.get("messages")
    if messages_param is not None:
        return messages_param.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    if not parameters:
        return False
    first = parameters[0]
    return first.kind in {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }


def _extract_chat_content(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and "content" in message:
                    content = message["content"]
                    if isinstance(content, str):
                        return content
                text = first.get("text")
                if isinstance(text, str):
                    return text
        content = response.get("content")
        if isinstance(content, str):
            return content
    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return text
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    raise ValueError("invalid_response: unsupported official client response")


def _question_id_from_metadata(metadata: dict[str, Any]) -> str:
    for key in ("idx", "question_id", "id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return "unknown"


def _safe_error(error_type: str, message: str) -> dict[str, str]:
    return sanitize_protocol_metadata(
        {
            "type": error_type,
            "message": message,
        }
    )


def _final_response_from_result(result: SolveResult) -> str:
    value = (result.final_answer.value or "").strip()
    if value:
        return value
    boxed = (result.final_answer.boxed or "").strip()
    if boxed:
        return boxed
    for step in reversed(result.visible_solution_steps):
        text = str(step or "").strip()
        if text:
            return text[:1000]
    return "Unable to produce a final answer."


def _trace_from_result(result: SolveResult) -> list[dict[str, str]]:
    trace: list[dict[str, str]] = [
        {
            "step": "route",
            "content": (
                f"domain={result.domain}; problem_type={result.problem_type}; "
                f"status={result.status}"
            ),
        }
    ]
    if result.visible_solution_steps:
        trace.append(
            {
                "step": "solve",
                "content": str(result.visible_solution_steps[-1])[:2000],
            }
        )
    if result.tool_trace:
        trace.append(
            {
                "step": "tools",
                "content": "; ".join(
                    f"{item.tool}:{item.status}:{item.summary}"
                    for item in result.tool_trace[:3]
                )[:2000],
            }
        )
    trace.append(
        {
            "step": "verify",
            "content": (
                f"{result.verification.method}; passed={result.verification.passed}; "
                f"{result.verification.notes}"
            )[:2000],
        }
    )
    if result.error:
        trace.append({"step": "error", "content": result.error[:1000]})
    return sanitize_protocol_metadata({"trace": trace})["trace"]


class ReasoningAgent:
    """Official preliminary-round entry point.

    The platform initializes this class with its official client:

        agent = ReasoningAgent(client=official_client)

    Then it calls:

        agent.solve(problem, metadata)
    """

    def __init__(self, client: Any | None = None, *args: Any, **kwargs: Any) -> None:
        _ = args
        self._metadata_keys_used = ("idx", "question_id", "id")
        run_mode = str(kwargs.get("run_mode", "fast"))
        enable_tools = bool(kwargs.get("enable_tools", True))
        max_refine_rounds = kwargs.get("max_refine_rounds", 0)
        if (
            isinstance(max_refine_rounds, bool)
            or not isinstance(max_refine_rounds, int)
            or not 0 <= max_refine_rounds <= 3
        ):
            raise ValueError("max_refine_rounds must be an integer between 0 and 3")
        prompt_config_path = kwargs.get(
            "prompt_config_path", REPO_ROOT / "configs" / "prompts.yaml"
        )
        temperature = float(kwargs.get("temperature", 0.2))
        max_tokens = int(kwargs.get("max_tokens", 4096))
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError("temperature is outside the safe range")
        if not 1 <= max_tokens <= 32_768:
            raise ValueError("max_tokens is outside the safe range")

        if client is None:
            adapted_client: Any = InternS1Client(mock=True)
            mock = True
        else:
            adapted_client = _OfficialClientAdapter(
                client,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            mock = False

        self._pipeline = MathAgentPipeline(
            client=adapted_client,
            prompt_config_path=prompt_config_path,
            mock=mock,
            enable_tools=enable_tools,
            max_refine_rounds=max_refine_rounds,
            save_trace=False,
            run_mode=run_mode,
        )

    def solve(self, problem: str, metadata: dict[str, Any] | None = None) -> dict:
        safe_metadata = metadata if isinstance(metadata, dict) else {}
        question_id = _question_id_from_metadata(safe_metadata)
        try:
            validated = MathQuestion.model_validate(
                {"question": problem, "question_id": question_id}
            )
            result = self._pipeline.solve(validated.question, validated.question_id)
            final_response = _final_response_from_result(result)
            success = is_semantically_successful(result) and bool(
                final_response.strip()
            )
            payload: dict[str, Any] = {
                "success": success,
                "status": result.status,
                "final_response": final_response,
                "trace": _trace_from_result(result),
            }
            if result.error:
                payload["error"] = _safe_error("PipelineError", result.error)
            return sanitize_protocol_metadata(payload)
        except Exception as exc:
            exception_type = type(exc).__name__
            exception_text = safe_exception_text(exc)
            return sanitize_protocol_metadata(
                {
                    "success": False,
                    "status": "error",
                    "final_response": "Unable to produce a final answer.",
                    "trace": [
                        {
                            "step": "error",
                            "content": f"{exception_type}: {exception_text}",
                        }
                    ],
                    "error": _safe_error(exception_type, exception_text),
                }
            )
