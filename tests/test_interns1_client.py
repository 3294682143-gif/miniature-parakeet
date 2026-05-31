from __future__ import annotations

import pytest
import requests

from math_agent.clients.interns1_client import InternS1Client


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


@pytest.fixture(autouse=True)
def _clear_real_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNS1_API_KEY", raising=False)
    monkeypatch.delenv("INTERNS1_BASE_URL", raising=False)
    monkeypatch.delenv("INTERNS1_MODEL", raising=False)


def test_chat_returns_stable_string_in_mock_mode() -> None:
    client = InternS1Client(mock=True)
    out = client.chat(messages=[{"role": "user", "content": "hi"}])
    assert isinstance(out, str)
    assert out == InternS1Client.MOCK_RESPONSE


def test_real_mode_missing_api_key_raises() -> None:
    client = InternS1Client(api_key=None, base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="api_key"):
        client.chat(messages=[{"role": "user", "content": "x"}])


def test_real_mode_missing_base_url_raises() -> None:
    client = InternS1Client(api_key="dummy", base_url=None, mock=False)
    with pytest.raises(ValueError, match="base_url"):
        client.chat(messages=[{"role": "user", "content": "x"}])


def test_error_message_does_not_include_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "super-secret-key"

    def _post(*args, **kwargs):
        return DummyResponse(status_code=401)

    monkeypatch.setattr("requests.post", _post)

    client = InternS1Client(api_key=secret, base_url="https://example.com", mock=False)
    with pytest.raises(ValueError) as exc:
        client.chat(messages=[{"role": "user", "content": "x"}])
    assert secret not in str(exc.value)


def test_network_error_does_not_chain_sensitive_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "super-secret-key"

    def _post(*args, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr("requests.post", _post)

    client = InternS1Client(api_key=secret, base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="network request failed") as exc:
        client.chat(messages=[{"role": "user", "content": "x"}])
    assert secret not in str(exc.value)
    assert exc.value.__cause__ is None


def test_payload_contains_model_and_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse(
            status_code=200, payload={"choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr("requests.post", _post)

    client = InternS1Client(
        api_key="dummy",
        base_url="https://example.com/v1",
        model="intern-s1",
        mock=False,
    )
    out = client.chat(messages=[{"role": "user", "content": "question"}])

    assert out == "ok"
    assert captured["json"]["model"] == "intern-s1"
    assert captured["json"]["messages"] == [{"role": "user", "content": "question"}]


def test_timeout_and_retries_can_be_set_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_TIMEOUT", "123")
    monkeypatch.setenv("INTERNS1_MAX_RETRIES", "4")
    client = InternS1Client(
        api_key="dummy",
        base_url="https://example.com/v1",
        model="intern-s1",
        mock=False,
    )
    assert client.timeout == 123
    assert client.max_retries == 4


def test_invalid_timeout_env_keeps_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNS1_TIMEOUT", "bad")
    monkeypatch.setenv("INTERNS1_MAX_RETRIES", "0")
    client = InternS1Client(
        api_key="dummy",
        base_url="https://example.com/v1",
        model="intern-s1",
        timeout=77,
        max_retries=3,
        mock=False,
    )
    assert client.timeout == 77
    assert client.max_retries == 3


def test_base_url_append_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def _post(url, headers, json, timeout):
        urls.append(url)
        return DummyResponse(
            status_code=200, payload={"choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr("requests.post", _post)

    client1 = InternS1Client(
        api_key="dummy", base_url="https://example.com/v1", mock=False
    )
    client1.chat(messages=[{"role": "user", "content": "q"}])

    client2 = InternS1Client(
        api_key="dummy", base_url="https://example.com/chat/completions", mock=False
    )
    client2.chat(messages=[{"role": "user", "content": "q"}])

    assert urls[0] == "https://example.com/v1/chat/completions"
    assert urls[1] == "https://example.com/chat/completions"


def test_4xx_should_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _post(url, headers, json, timeout):
        calls["count"] += 1
        return DummyResponse(status_code=400)

    monkeypatch.setattr("requests.post", _post)

    client = InternS1Client(
        api_key="dummy", base_url="https://example.com", mock=False, max_retries=3
    )
    with pytest.raises(ValueError, match="HTTP 400"):
        client.chat(messages=[{"role": "user", "content": "q"}])
    assert calls["count"] == 1


def test_5xx_should_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _post(url, headers, json, timeout):
        calls["count"] += 1
        if calls["count"] < 2:
            return DummyResponse(status_code=500)
        return DummyResponse(
            status_code=200, payload={"choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr("requests.post", _post)

    client = InternS1Client(
        api_key="dummy", base_url="https://example.com", mock=False, max_retries=2
    )
    out = client.chat(messages=[{"role": "user", "content": "q"}])
    assert out == "ok"
    assert calls["count"] == 2


def test_invalid_response_shape_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    def _post(url, headers, json, timeout):
        return DummyResponse(status_code=200, payload={"choices": []})

    monkeypatch.setattr("requests.post", _post)

    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="invalid_response"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_invalid_json_response_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadJsonResponse(DummyResponse):
        def json(self) -> dict:
            raise ValueError("bad json")

    def _post(url, headers, json, timeout):
        return BadJsonResponse(status_code=200)

    monkeypatch.setattr("requests.post", _post)

    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="invalid_response"):
        client.chat(messages=[{"role": "user", "content": "q"}])
