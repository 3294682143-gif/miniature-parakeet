# safety: allow-secret-fixtures
from __future__ import annotations

import json
from typing import Any

import pytest

from user_agent import ReasoningAgent


def _is_verifier_call(messages: list[dict[str, Any]]) -> bool:
    return any(
        "Return JSON with method/passed/notes" in str(message.get("content", ""))
        for message in messages
    )


class FakeOfficialClient:
    model = "fake-official"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if _is_verifier_call(messages):
            return '{"method":"self_review","passed":true,"notes":"verified"}'
        return "Compute directly: 2+3=5, so the final answer is \\boxed{5}."


class PositionalOnlyOfficialClient:
    model = "positional-only-official"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        /,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if _is_verifier_call(messages):
            return '{"method":"self_review","passed":true,"notes":"verified"}'
        return "Final answer: \\boxed{8}"


class KeywordOnlyOfficialClient:
    model = "keyword-only-official"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if _is_verifier_call(messages):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"method":"self_review","passed":true,"notes":"verified"}'
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "Final answer: \\boxed{9}"}}]}


class RaisingOfficialClient:
    model = "raising-official"

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        _ = messages, temperature, max_tokens
        raise RuntimeError("model unavailable")


def test_reasoning_agent_matches_official_entry_contract() -> None:
    client = FakeOfficialClient()
    agent = ReasoningAgent(client=client)

    output = agent.solve("Compute 2+3.", {"idx": 7, "answer": "5"})

    assert output["success"] is True
    assert output["status"] == "success"
    assert output["final_response"] == "5"
    assert isinstance(output["trace"], list)
    assert client.calls
    json.dumps(output, ensure_ascii=False)


def test_reasoning_agent_accepts_positional_only_official_client() -> None:
    client = PositionalOnlyOfficialClient()
    agent = ReasoningAgent(client=client)

    output = agent.solve("Compute 4+4.", {"idx": "pos"})

    assert output["success"] is True
    assert output["final_response"] == "8"
    assert client.calls
    json.dumps(output, ensure_ascii=False)


def test_reasoning_agent_accepts_keyword_only_official_client_response_dict() -> None:
    client = KeywordOnlyOfficialClient()
    agent = ReasoningAgent(client=client)

    output = agent.solve("Compute 4+5.", {"idx": "kw"})

    assert output["success"] is True
    assert output["final_response"] == "9"
    assert client.calls
    json.dumps(output, ensure_ascii=False)


def test_reasoning_agent_failure_is_jsonable_and_nonempty() -> None:
    agent = ReasoningAgent(client=RaisingOfficialClient(), enable_tools=False)

    output = agent.solve("Find x if x+1=2.", {"idx": "bad"})

    assert output["success"] is False
    assert output["final_response"]
    assert output["error"]["type"] == "PipelineError"
    assert "model unavailable" in output["error"]["message"]
    json.dumps(output, ensure_ascii=False)


def test_reasoning_agent_bounds_problem_and_official_response() -> None:
    agent = ReasoningAgent(client=FakeOfficialClient())
    oversized_problem = "x" * 32_769

    output = agent.solve(oversized_problem, {"idx": "large"})

    assert output["success"] is False
    assert output["status"] == "error"

    class OversizedClient:
        model = "oversized"

        def chat(self, messages, **kwargs):
            return "x" * (2 * 1024 * 1024 + 1)

    oversized_output = ReasoningAgent(client=OversizedClient()).solve(
        "What is 1+1?", {"idx": "response"}
    )
    assert oversized_output["success"] is False


def test_official_adapter_rejects_unknown_message_fields() -> None:
    agent = ReasoningAgent(client=FakeOfficialClient())

    with pytest.raises(ValueError, match="safe schema"):
        agent._pipeline.client.chat([{"role": "user", "content": "q", "extra": "x"}])


def test_reasoning_agent_failure_redacts_credentials_from_trace() -> None:
    secret = "sk-USER_AGENT_SECRET_VALUE_123456"

    class SecretRaisingClient:
        model = "secret-raising"

        def chat(self, messages, **kwargs):
            _ = messages, kwargs
            raise RuntimeError(secret)

    output = ReasoningAgent(client=SecretRaisingClient()).solve("q", {"idx": "q1"})

    rendered = json.dumps(output, ensure_ascii=False)
    assert secret not in rendered
    assert "[REDACTED]" in rendered


def test_reasoning_agent_failure_redacts_uri_userinfo() -> None:
    secret = "https://reviewer:SUPER_SECRET_PASSWORD@example.invalid/api"

    class SecretRaisingClient:
        model = "secret-uri-raising"

        def chat(self, messages, **kwargs):
            _ = messages, kwargs
            raise RuntimeError(secret)

    output = ReasoningAgent(client=SecretRaisingClient()).solve("q", {"idx": "q1"})

    rendered = json.dumps(output, ensure_ascii=False)
    assert secret not in rendered
    assert "https://[REDACTED]@example.invalid/api" in rendered


def test_reasoning_agent_handles_exception_with_broken_string_conversion() -> None:
    secret = "MOCK_BROKEN_EXCEPTION_SECRET"

    class UnprintableError(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError(f"AWS_SECRET_ACCESS_KEY={secret}")

    agent = ReasoningAgent(client=FakeOfficialClient())

    def fail_solve(*_args, **_kwargs):
        raise UnprintableError()

    agent._pipeline.solve = fail_solve
    output = agent.solve("q", {"idx": "broken-string"})
    rendered = json.dumps(output, ensure_ascii=False)

    assert output["success"] is False
    assert output["error"]["type"] == "UnprintableError"
    assert "message unavailable" in output["error"]["message"]
    assert secret not in rendered


def test_reasoning_agent_redacts_short_and_extended_assignments() -> None:
    message = (
        "api_key=x password=y AWS_SECRET_ACCESS_KEY=MOCK_AWS_VALUE "
        "CLIENT_SECRET_VALUE=MOCK_CLIENT_VALUE"
    )
    agent = ReasoningAgent(client=FakeOfficialClient())

    def fail_solve(*_args, **_kwargs):
        raise RuntimeError(message)

    agent._pipeline.solve = fail_solve
    rendered = json.dumps(agent.solve("q", {"idx": "secret"}), ensure_ascii=False)

    assert "api_key=x" not in rendered
    assert "password=y" not in rendered
    assert "MOCK_AWS_VALUE" not in rendered
    assert "MOCK_CLIENT_VALUE" not in rendered
    assert "[REDACTED]" in rendered
