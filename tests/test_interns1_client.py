# safety: allow-secret-fixtures
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import requests

import math_agent.clients.interns1_client as client_module
from math_agent.clients.interns1_client import InternS1Client

_REAL_ISOLATED_HTTP = client_module._run_isolated_http


def _address_info(address: str, port: int | str = 443) -> tuple[object, ...]:
    if ":" in address:
        return (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, port, 0, 0),
        )
    return (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        (address, port),
    )


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers: dict[str, str] = {}
        self.closed = False

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size: int):
        raw = json.dumps(self._payload).encode("utf-8")
        for offset in range(0, len(raw), chunk_size):
            yield raw[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_real_api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNS1_API_KEY", raising=False)
    monkeypatch.delenv("INTERNS1_BASE_URL", raising=False)
    monkeypatch.delenv("INTERNS1_MODEL", raising=False)
    monkeypatch.setenv("INTERNS1_ALLOWED_HOSTS", "example.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [_address_info("8.8.8.8", port)],
    )
    monkeypatch.setattr(
        client_module,
        "_run_isolated_http",
        lambda request, wall_timeout: client_module._perform_http_request(request),
    )


def test_chat_returns_stable_string_in_mock_mode() -> None:
    client = InternS1Client(mock=True)
    out = client.chat(messages=[{"role": "user", "content": "hi"}])
    assert isinstance(out, str)
    assert out == InternS1Client.MOCK_RESPONSE


def test_mock_mode_ignores_invalid_real_api_host_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_ALLOWED_HOSTS", "https://invalid.example/*")

    client = InternS1Client(mock=True)

    assert client.chat([{"role": "user", "content": "hi"}]) == client.MOCK_RESPONSE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"messages": "not-a-list"},
        {"messages": [{"role": "user", "content": "q"}], "top_p": 9},
        {"messages": [{"role": "user", "content": "q"}], "max_tokens": 0},
    ],
)
def test_mock_mode_still_validates_request_contract(kwargs: dict[str, object]) -> None:
    client = InternS1Client(mock=True)

    with pytest.raises(ValueError, match="invalid_request"):
        client.chat(**kwargs)


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

    monkeypatch.setattr("requests.Session.post", _post)

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

    monkeypatch.setattr("requests.Session.post", _post)

    client = InternS1Client(api_key=secret, base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="network request failed") as exc:
        client.chat(messages=[{"role": "user", "content": "x"}])
    assert secret not in str(exc.value)
    assert exc.value.__cause__ is None


def test_transport_ignores_netrc_and_keeps_configured_bearer_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    netrc_path = tmp_path / "netrc-fixture"
    netrc_path.write_text(
        "machine example.com login intruder password fixture-password-1234\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NETRC", str(netrc_path))
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8080")
    captured: dict[str, object] = {"closed": False}
    original_close = requests.sessions.Session.close

    def _send(
        session: requests.Session,
        request: requests.PreparedRequest,
        **kwargs: object,
    ) -> DummyResponse:
        captured["authorization"] = request.headers.get("Authorization")
        captured["trust_env"] = session.trust_env
        captured["proxies"] = kwargs.get("proxies")
        return DummyResponse(status_code=401)

    def _close(session: requests.Session) -> None:
        captured["closed"] = True
        original_close(session)

    monkeypatch.setattr(requests.sessions.Session, "send", _send)
    monkeypatch.setattr(requests.sessions.Session, "close", _close)

    result = client_module._perform_http_request(
        {
            "url": "https://example.com/v1/chat/completions",
            "api_key": "configured-fixture-key-1234",
            "payload": {"model": "fixture-model"},
            "timeout": 1,
        }
    )

    assert result == {"ok": True, "status": 401, "body": ""}
    assert captured["authorization"] == "Bearer configured-fixture-key-1234"
    assert captured["trust_env"] is False
    assert captured["proxies"] == {}
    assert captured["closed"] is True


@pytest.mark.parametrize(
    "resolved_addresses",
    [
        ("127.0.0.1",),
        ("10.23.45.67",),
        ("169.254.10.20",),
        ("::1",),
        ("fd00::1234",),
        ("fe80::1234",),
        ("8.8.8.8", "127.0.0.1"),
    ],
)
def test_transport_rejects_non_global_dns_destinations_before_bearer_send(
    monkeypatch: pytest.MonkeyPatch, resolved_addresses: tuple[str, ...]
) -> None:
    post_calls = 0

    def _getaddrinfo(host, port, *args, **kwargs):
        return [_address_info(address, port) for address in resolved_addresses]

    def _post(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        return DummyResponse(status_code=200)

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    monkeypatch.setattr("requests.Session.post", _post)

    result = client_module._perform_http_request(
        {
            "url": "https://example.com/v1/chat/completions",
            "api_key": "configured-fixture-key-1234",
            "payload": {"model": "fixture-model"},
            "timeout": 1,
        }
    )

    assert result == {"ok": False, "error": "blocked_destination"}
    assert post_calls == 0


def test_client_surfaces_blocked_dns_destination_without_retrying_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_calls = 0
    post_calls = 0

    def _getaddrinfo(host, port, *args, **kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        return [_address_info("127.0.0.1", port)]

    def _post(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        return DummyResponse(status_code=200)

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    monkeypatch.setattr("requests.Session.post", _post)
    client = InternS1Client(
        api_key="configured-fixture-key-1234",
        base_url="https://example.com/v1",
        max_retries=5,
        mock=False,
    )

    with pytest.raises(ValueError, match="security_error:.*public"):
        client.chat(messages=[{"role": "user", "content": "question"}])

    assert resolver_calls == 1
    assert post_calls == 0


def test_transport_pins_one_public_dns_resolution_for_the_https_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    underlying_calls: list[tuple[object, object]] = []
    observed: dict[str, object] = {}

    def _getaddrinfo(host, port, *args, **kwargs):
        underlying_calls.append((host, port))
        address = "8.8.8.8" if len(underlying_calls) == 1 else "127.0.0.1"
        return [_address_info(address, port)]

    def _post(*args, **kwargs):
        observed["calls_before_post"] = len(underlying_calls)
        observed["connection_addresses"] = socket.getaddrinfo(
            "example.com", 443, type=socket.SOCK_STREAM
        )
        return DummyResponse(status_code=401)

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    monkeypatch.setattr("requests.Session.post", _post)

    result = client_module._perform_http_request(
        {
            "url": "https://example.com/v1/chat/completions",
            "api_key": "configured-fixture-key-1234",
            "payload": {"model": "fixture-model"},
            "timeout": 1,
        }
    )

    assert result == {"ok": True, "status": 401, "body": ""}
    assert observed["calls_before_post"] == 1
    assert len(underlying_calls) == 1
    assert observed["connection_addresses"] == [_address_info("8.8.8.8")]
    assert socket.getaddrinfo is _getaddrinfo


def test_worker_environment_omits_home_and_proxy_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = {
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "USERPROFILE",
        "NETRC",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    }
    for name in blocked:
        monkeypatch.setenv(name, f"fixture-{name.casefold()}")

    worker_environment = client_module._worker_environment()

    assert blocked.isdisjoint({name.upper() for name in worker_environment})


def test_payload_contains_model_and_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        captured["allow_redirects"] = allow_redirects
        return DummyResponse(
            status_code=200, payload={"choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr("requests.Session.post", _post)

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
    assert captured["allow_redirects"] is False


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


def test_explicit_limits_take_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_TIMEOUT", "300")
    monkeypatch.setenv("INTERNS1_MAX_RETRIES", "5")

    client = InternS1Client(timeout=1, max_retries=1, mock=True)

    assert client.timeout == 1
    assert client.max_retries == 1


def test_explicit_empty_real_config_does_not_fall_back_to_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_API_KEY", "mock-environment-value")
    monkeypatch.setenv("INTERNS1_BASE_URL", "https://example.com")
    client = InternS1Client(api_key="", base_url="", mock=False)

    with pytest.raises(ValueError, match="missing_api_key"):
        client.chat(messages=[{"role": "user", "content": "q"}])


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeout", 0),
        ("timeout", True),
        ("timeout", 2.5),
        ("max_retries", 0),
        ("max_retries", True),
        ("max_retries", 2.5),
    ],
)
def test_constructor_rejects_invalid_numeric_limits(field: str, value: object) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match=field):
        InternS1Client(
            api_key="dummy", base_url="https://example.com", mock=False, **kwargs
        )


def test_base_url_append_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        urls.append(url)
        return DummyResponse(
            status_code=200, payload={"choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr("requests.Session.post", _post)

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

    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        calls["count"] += 1
        return DummyResponse(status_code=400)

    monkeypatch.setattr("requests.Session.post", _post)

    client = InternS1Client(
        api_key="dummy", base_url="https://example.com", mock=False, max_retries=3
    )
    with pytest.raises(ValueError, match="HTTP 400"):
        client.chat(messages=[{"role": "user", "content": "q"}])
    assert calls["count"] == 1


def test_redirect_response_is_never_accepted_as_chat_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        return DummyResponse(
            status_code=302,
            payload={"choices": [{"message": {"content": "forged-success"}}]},
        )

    monkeypatch.setattr("requests.Session.post", _post)
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    with pytest.raises(ValueError, match="redirects"):
        client.chat(messages=[{"role": "user", "content": "q"}])


@pytest.mark.parametrize("status", [101, 201, 700])
def test_only_http_200_is_accepted(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setattr(
        "requests.Session.post",
        lambda *args, **kwargs: DummyResponse(
            status_code=status,
            payload={"choices": [{"message": {"content": "forged-success"}}]},
        ),
    )
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    with pytest.raises(ValueError, match="unexpected HTTP"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_isolated_transport_kills_a_worker_at_the_wall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"killed": False, "closed": False}

    class FakeJob:
        def close(self) -> None:
            state["closed"] = True

    class HangingProcess:
        pid = 123
        args = ["worker"]
        returncode: int | None = None

        def communicate(self, input=None, timeout=None):
            if not state["killed"]:
                raise client_module.subprocess.TimeoutExpired(self.args, timeout)
            self.returncode = -9
            return b"", b""

        def kill(self) -> None:
            state["killed"] = True
            self.returncode = -9

        def poll(self):
            return self.returncode

    monkeypatch.setattr(
        client_module.subprocess, "Popen", lambda *a, **k: HangingProcess()
    )
    monkeypatch.setattr(
        client_module,
        "assign_windows_job_limits",
        lambda *args, **kwargs: FakeJob(),
    )

    result = _REAL_ISOLATED_HTTP(
        {"url": "https://example.com", "api_key": "mock", "payload": {}, "timeout": 1},
        0.01,
    )

    assert result == {"ok": False, "error": "timeout"}
    assert state["killed"] is True
    assert state["closed"] is (client_module.os.name == "nt")


def test_5xx_should_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        calls["count"] += 1
        if calls["count"] < 2:
            return DummyResponse(status_code=500)
        return DummyResponse(
            status_code=200, payload={"choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr("requests.Session.post", _post)

    client = InternS1Client(
        api_key="dummy", base_url="https://example.com", mock=False, max_retries=2
    )
    out = client.chat(messages=[{"role": "user", "content": "q"}])
    assert out == "ok"
    assert calls["count"] == 2


def test_invalid_response_shape_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        return DummyResponse(status_code=200, payload={"choices": []})

    monkeypatch.setattr("requests.Session.post", _post)

    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="invalid_response"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_invalid_json_response_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadJsonResponse(DummyResponse):
        def iter_content(self, chunk_size: int):
            yield b"bad json"

    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        return BadJsonResponse(status_code=200)

    monkeypatch.setattr("requests.Session.post", _post)

    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="invalid_response"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_duplicate_http_response_keys_are_classified_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DuplicateJsonResponse(DummyResponse):
        def iter_content(self, chunk_size: int):
            yield (
                b'{"choices":[{"message":{"content":"safe"}}],'
                b'"choices":[{"message":{"content":"shadowed"}}]}'
            )

    monkeypatch.setattr(
        "requests.Session.post",
        lambda *args, **kwargs: DuplicateJsonResponse(status_code=200),
    )

    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)
    with pytest.raises(ValueError, match="invalid_response"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_isolated_http_rejects_duplicate_worker_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        pid = 123
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return b'{"ok":true,"status":200,"status":201,"body":""}', b""

        def poll(self):
            return 0

        def kill(self):
            self.returncode = -9

    class Job:
        def close(self):
            return None

    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(
        client_module, "assign_windows_job_limits", lambda *args, **kwargs: Job()
    )

    result = _REAL_ISOLATED_HTTP(
        {"url": "https://example.com", "api_key": "mock", "payload": {}, "timeout": 1},
        1,
    )

    assert result == {"ok": False, "error": "invalid_response"}


def test_http_worker_rejects_duplicate_request_keys() -> None:
    worker = Path(client_module.__file__).with_name("http_worker.py")
    completed = subprocess.run(
        [sys.executable, "-E", str(worker)],
        input=(
            b'{"url":"https://example.com","url":"bad://",'
            b'"api_key":"mock","payload":{},"timeout":1}'
        ),
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com/v1",
        "https://user:password@example.com/v1",
        "https://example.com/v1?token=value",
        "https://example.com/v1#fragment",
    ],
)
def test_real_mode_rejects_unsafe_base_urls(base_url: str) -> None:
    client = InternS1Client(api_key="dummy", base_url=base_url, mock=False)

    with pytest.raises(ValueError, match="invalid_base_url") as exc:
        client.chat(messages=[{"role": "user", "content": "q"}])

    assert "password" not in str(exc.value)


def test_real_mode_requires_an_explicit_api_host_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTERNS1_ALLOWED_HOSTS", raising=False)
    monkeypatch.setattr(
        client_module,
        "_run_isolated_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("transport must not be reached")
        ),
    )
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    with pytest.raises(ValueError, match="allowed_hosts"):
        client.chat(messages=[{"role": "user", "content": "q"}])


@pytest.mark.parametrize(
    "base_url,allowed_host",
    [
        ("https://127.0.0.1/v1", "127.0.0.1"),
        ("https://localhost/v1", "localhost"),
        ("https://[::1]/v1", "::1"),
        ("https://2130706433/v1", "2130706433"),
        ("https://0177.0.0.1/v1", "0177.0.0.1"),
        ("https://intranet/v1", "intranet"),
    ],
)
def test_real_mode_rejects_local_api_hosts_even_when_allowlisted(
    monkeypatch: pytest.MonkeyPatch, base_url: str, allowed_host: str
) -> None:
    monkeypatch.setenv("INTERNS1_ALLOWED_HOSTS", allowed_host)
    monkeypatch.setattr(
        client_module,
        "_run_isolated_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("transport must not be reached")
        ),
    )
    client = InternS1Client(api_key="dummy", base_url=base_url, mock=False)

    with pytest.raises(ValueError, match="invalid_base_url"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_real_mode_rejects_a_host_outside_the_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setattr(
        client_module,
        "_run_isolated_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("transport must not be reached")
        ),
    )
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    with pytest.raises(ValueError, match="disallowed_host"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_real_mode_host_allowlist_does_not_authorize_nondefault_https_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_ALLOWED_HOSTS", "example.com")
    monkeypatch.setattr(
        client_module,
        "_run_isolated_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("transport must not be reached")
        ),
    )
    client = InternS1Client(
        api_key="dummy", base_url="https://example.com:8443/v1", mock=False
    )

    with pytest.raises(ValueError, match="disallowed_origin"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_http_worker_rejects_nondefault_https_port_before_bearer_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests.Session,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Bearer transport must not be reached")
        ),
    )

    result = client_module._perform_http_request(
        {
            "url": "https://example.com:8443/v1/chat/completions",
            "api_key": "dummy",
            "payload": {},
            "timeout": 1,
        }
    )

    assert result == {"ok": False, "error": "blocked_destination"}


def test_real_mode_keeps_default_https_origin_compatible_when_port_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def _post(session, url, headers, json, timeout, stream, allow_redirects):
        captured["url"] = url
        return DummyResponse(
            status_code=200, payload={"choices": [{"message": {"content": "ok"}}]}
        )

    monkeypatch.setattr(requests.Session, "post", _post)
    client = InternS1Client(
        api_key="dummy", base_url="https://example.com:443/v1", mock=False
    )

    assert client.chat(messages=[{"role": "user", "content": "q"}]) == "ok"
    assert captured["url"] == "https://example.com:443/v1/chat/completions"


def test_real_mode_preflight_validates_the_host_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_ALLOWED_HOSTS", "api.example.com")
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    with pytest.raises(ValueError, match="disallowed_host"):
        client._validate_real_mode_config()


def test_retry_timeout_and_response_size_have_hard_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNS1_TIMEOUT", "999999")
    monkeypatch.setenv("INTERNS1_MAX_RETRIES", "999999")
    client = InternS1Client(
        api_key="dummy",
        base_url="https://example.com",
        mock=False,
    )
    assert client.timeout <= 300
    assert client.max_retries <= 5
    with pytest.raises(ValueError, match="timeout"):
        InternS1Client(
            api_key="dummy",
            base_url="https://example.com",
            timeout=999999,
            max_retries=2,
            mock=False,
        )

    response = DummyResponse(
        status_code=200,
        payload={"choices": [{"message": {"content": "ok"}}]},
    )
    response.headers["Content-Length"] = str(3 * 1024 * 1024)
    monkeypatch.setattr("requests.Session.post", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="size limit"):
        client.chat(messages=[{"role": "user", "content": "q"}])


def test_request_schema_and_sampling_values_are_bounded() -> None:
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    with pytest.raises(ValueError, match="safe schema"):
        client.chat(messages=[{"role": "user", "content": object()}])
    with pytest.raises(ValueError, match="sampling"):
        client.chat(messages=[{"role": "user", "content": "q"}], top_p=float("nan"))
    with pytest.raises(ValueError, match="max_tokens"):
        client.chat(messages=[{"role": "user", "content": "q"}], max_tokens=100_000)
    with pytest.raises(ValueError, match="safe schema"):
        client.chat(
            messages=[
                {
                    "role": "user",
                    "content": "q",
                    "unbounded_extra": "x" * 1_000_001,
                }
            ]
        )


def test_streaming_response_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    response = DummyResponse(
        status_code=200,
        payload={"choices": [{"message": {"content": "ok"}}]},
    )
    monkeypatch.setattr("requests.Session.post", lambda *args, **kwargs: response)
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    assert client.chat(messages=[{"role": "user", "content": "q"}]) == "ok"
    assert response.closed is True


def test_serialized_unicode_request_size_is_bounded_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "requests.Session.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("network must not be reached")
        ),
    )
    client = InternS1Client(api_key="dummy", base_url="https://example.com", mock=False)

    with pytest.raises(ValueError, match="serialized request"):
        client.chat(messages=[{"role": "user", "content": "\U0001f600" * 200_000}])
