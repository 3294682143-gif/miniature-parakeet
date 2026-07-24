from __future__ import annotations

import base64
import ipaddress
import json
import math
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from math_agent.io_utils import strict_json_loads
from math_agent.process_isolation import (
    ProcessCapacityError,
    WindowsJobLimits,
    assign_windows_job_limits,
    isolated_process_slot,
)

MAX_TIMEOUT_SECONDS = 300
MAX_RETRIES = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_CHARS = 1_000_000
MAX_TOKENS = 32_768
MAX_MESSAGES = 256
MAX_MODEL_CHARS = 256
MAX_TOTAL_CHAT_SECONDS = 300
MAX_HTTP_WORKER_REQUEST_BYTES = MAX_REQUEST_CHARS + 32 * 1024
MAX_HTTP_WORKER_RESPONSE_BYTES = 3 * MAX_RESPONSE_BYTES
HTTP_WORKER_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
HTTP_WORKER_CPU_LIMIT_SECONDS = 30
MAX_ALLOWED_API_HOSTS = 32


def _normalize_api_hostname(value: str) -> str:
    candidate = value.strip().rstrip(".")
    if not candidate or len(candidate) > 253:
        raise ValueError("invalid_allowed_hosts: host is outside the safe schema")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    if any(character in candidate for character in ("/", "\\", "@", ":", "*")):
        raise ValueError("invalid_allowed_hosts: exact hostnames are required")
    try:
        normalized = candidate.encode("idna").decode("ascii").casefold()
    except UnicodeError:
        raise ValueError("invalid_allowed_hosts: hostname is malformed") from None
    labels = normalized.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or any(not (character.isalnum() or character == "-") for character in label)
        for label in labels
    ):
        raise ValueError("invalid_allowed_hosts: hostname is malformed")
    return normalized


def _parse_allowed_api_hosts(value: str | None) -> frozenset[str]:
    if value is None or not value.strip():
        return frozenset()
    parts = [part.strip() for part in value.split(",")]
    if len(parts) > MAX_ALLOWED_API_HOSTS or any(not part for part in parts):
        raise ValueError("invalid_allowed_hosts: too many or empty host entries")
    return frozenset(_normalize_api_hostname(part) for part in parts)


def _api_host_is_local_or_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return (
        "." not in host
        or all(label.isdigit() for label in host.split("."))
        or host == "localhost"
        or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))
    )


class _InvalidDestinationError(Exception):
    pass


class _BlockedDestinationError(Exception):
    pass


class _DestinationResolutionError(Exception):
    pass


def _resolved_record_is_global(
    record: object,
    *,
    expected_port: int,
) -> bool:
    if not isinstance(record, tuple) or len(record) != 5:
        return False
    family, socket_type, protocol, _canonical_name, socket_address = record
    if family not in {socket.AF_INET, socket.AF_INET6}:
        return False
    if socket_type != socket.SOCK_STREAM or protocol not in {
        0,
        socket.IPPROTO_TCP,
    }:
        return False
    if not isinstance(socket_address, tuple) or len(socket_address) < 2:
        return False
    address_text, resolved_port = socket_address[:2]
    if (
        not isinstance(address_text, str)
        or "%" in address_text
        or isinstance(resolved_port, bool)
        or not isinstance(resolved_port, int)
        or resolved_port != expected_port
    ):
        return False
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError:
        return False
    if (family == socket.AF_INET) != (address.version == 4):
        return False
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_private
        and not address.is_reserved
        and not address.is_unspecified
    )


def _normalize_lookup_hostname(value: object) -> str | None:
    if isinstance(value, bytes):
        try:
            candidate = value.decode("ascii", errors="strict")
        except UnicodeError:
            return None
    elif isinstance(value, str):
        candidate = value
    else:
        return None
    try:
        return _normalize_api_hostname(candidate)
    except ValueError:
        return None


@contextmanager
def _pinned_public_https_destination(url: str) -> Iterator[None]:
    """Resolve once, reject non-public addresses, and pin DNS inside one worker."""

    try:
        parsed = urlsplit(url)
        parsed_port = parsed.port
    except (TypeError, ValueError):
        raise _InvalidDestinationError from None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _InvalidDestinationError
    try:
        hostname = _normalize_api_hostname(parsed.hostname)
    except ValueError:
        raise _InvalidDestinationError from None
    if _api_host_is_local_or_literal(hostname):
        raise _BlockedDestinationError
    target_port = 443 if parsed_port is None else parsed_port
    if not 1 <= target_port <= 65_535:
        raise _InvalidDestinationError
    if target_port != 443:
        raise _BlockedDestinationError

    original_getaddrinfo = socket.getaddrinfo
    try:
        resolved = original_getaddrinfo(
            hostname,
            target_port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
        )
    except (OSError, TypeError, UnicodeError, ValueError):
        raise _DestinationResolutionError from None
    if not resolved:
        raise _DestinationResolutionError
    if any(
        not _resolved_record_is_global(record, expected_port=target_port)
        for record in resolved
    ):
        raise _BlockedDestinationError
    pinned_records = tuple(resolved)

    def _pinned_getaddrinfo(
        host: object,
        port: object,
        family: int = 0,
        type: int = 0,  # noqa: A002 - mirror socket.getaddrinfo's public signature.
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        del flags
        if (
            _normalize_lookup_hostname(host) != hostname
            or isinstance(port, bool)
            or not isinstance(port, (str, bytes, int))
        ):
            raise socket.gaierror(socket.EAI_NONAME, "destination is not pinned")
        try:
            normalized_port = int(port)
        except (TypeError, ValueError):
            raise socket.gaierror(
                socket.EAI_NONAME, "destination is not pinned"
            ) from None
        if normalized_port != target_port:
            raise socket.gaierror(socket.EAI_NONAME, "destination is not pinned")
        matches = [
            record
            for record in pinned_records
            if (family in {0, socket.AF_UNSPEC} or record[0] == family)
            and (type == 0 or record[1] == type)
            and (proto == 0 or record[2] in {0, proto})
        ]
        if not matches:
            raise socket.gaierror(socket.EAI_NONAME, "destination is not pinned")
        return matches

    # This mutation is process-local: production calls this helper only inside the
    # one-request HTTP worker. Keeping the hostname in the URL preserves TLS SNI,
    # certificate verification, and the HTTP Host header while the connection uses
    # the already-validated address records.
    setattr(socket, "getaddrinfo", _pinned_getaddrinfo)
    try:
        yield
    finally:
        setattr(socket, "getaddrinfo", original_getaddrinfo)


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    safe_default = default if 1 <= default <= maximum else maximum
    if value is None or value.strip() == "":
        return safe_default
    try:
        parsed = int(value)
    except ValueError:
        return safe_default
    return parsed if 1 <= parsed <= maximum else safe_default


def _strict_positive_int(
    value: int | None, default: int, maximum: int, name: str
) -> int:
    if value is None:
        return default
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= maximum
    ):
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")
    return value


def _worker_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _perform_http_request(request: dict[str, Any]) -> dict[str, Any]:
    """Perform one bounded request; used inside the killable transport worker."""

    if set(request) != {"url", "api_key", "payload", "timeout"}:
        return {"ok": False, "error": "invalid_request"}
    url = request.get("url")
    api_key = request.get("api_key")
    payload = request.get("payload")
    timeout = request.get("timeout")
    if (
        not isinstance(url, str)
        or not isinstance(api_key, str)
        or not isinstance(payload, dict)
        or isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0
    ):
        return {"ok": False, "error": "invalid_request"}
    session: requests.Session | None = None
    response: Any = None
    try:
        with _pinned_public_https_destination(url):
            session = requests.Session()
            # Disable implicit netrc authentication and environment proxy discovery
            # so the caller's explicit Authorization header remains authoritative.
            session.trust_env = False
            response = session.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=float(timeout),
                stream=True,
                allow_redirects=False,
            )
            status = response.status_code
            if isinstance(status, bool) or not isinstance(status, int):
                return {"ok": False, "error": "invalid_response"}
            if status != 200:
                return {"ok": True, "status": status, "body": ""}
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "invalid_response"}
                if declared_length < 0 or declared_length > MAX_RESPONSE_BYTES:
                    return {"ok": False, "error": "response_too_large"}
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                if not isinstance(chunk, (bytes, bytearray)):
                    return {"ok": False, "error": "invalid_response"}
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    return {"ok": False, "error": "response_too_large"}
                chunks.append(bytes(chunk))
            return {
                "ok": True,
                "status": status,
                "body": base64.b64encode(b"".join(chunks)).decode("ascii"),
            }
    except _InvalidDestinationError:
        return {"ok": False, "error": "invalid_request"}
    except _BlockedDestinationError:
        return {"ok": False, "error": "blocked_destination"}
    except _DestinationResolutionError:
        return {"ok": False, "error": "network"}
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException:
        return {"ok": False, "error": "network"}
    except Exception:
        return {"ok": False, "error": "invalid_response"}
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def _run_isolated_http_without_capacity_guard(
    request: dict[str, Any], wall_timeout: float
) -> dict[str, Any]:
    if (
        isinstance(wall_timeout, bool)
        or not isinstance(wall_timeout, (int, float))
        or not math.isfinite(float(wall_timeout))
        or float(wall_timeout) <= 0
    ):
        return {"ok": False, "error": "timeout"}
    encoded = json.dumps(
        request,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_HTTP_WORKER_REQUEST_BYTES:
        return {"ok": False, "error": "invalid_request"}
    worker = Path(__file__).with_name("http_worker.py")
    creationflags = (
        int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    )
    process: subprocess.Popen[bytes] | None = None
    job: WindowsJobLimits | None = None
    deadline = time.monotonic() + float(wall_timeout)
    try:
        process = subprocess.Popen(
            [sys.executable, "-E", str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_worker_environment(),
            creationflags=creationflags,
        )
        if os.name == "nt":
            job = assign_windows_job_limits(
                process.pid,
                memory_limit_bytes=HTTP_WORKER_MEMORY_LIMIT_BYTES,
                cpu_limit_seconds=HTTP_WORKER_CPU_LIMIT_SECONDS,
            )
            if job is None:
                process.kill()
                process.communicate()
                return {"ok": False, "error": "isolation_unavailable"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            process.communicate()
            return {"ok": False, "error": "timeout"}
        try:
            stdout, _ = process.communicate(input=encoded, timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return {"ok": False, "error": "timeout"}
        if process.returncode != 0 or len(stdout) > MAX_HTTP_WORKER_RESPONSE_BYTES:
            return {"ok": False, "error": "invalid_response"}
        response = strict_json_loads(stdout.decode("utf-8", errors="strict"))
        if not isinstance(response, dict):
            return {"ok": False, "error": "invalid_response"}
        return response
    except OSError:
        return {"ok": False, "error": "network"}
    except (RecursionError, TypeError, UnicodeError, ValueError):
        return {"ok": False, "error": "invalid_response"}
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if job is not None:
            job.close()


def _run_isolated_http(request: dict[str, Any], wall_timeout: float) -> dict[str, Any]:
    try:
        with isolated_process_slot():
            return _run_isolated_http_without_capacity_guard(request, wall_timeout)
    except ProcessCapacityError:
        return {"ok": False, "error": "capacity"}


class InternS1Client:
    DEFAULT_MODEL = "intern-s1"
    MOCK_RESPONSE = "[MOCK] Intern-S1 stable response"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        mock: bool = False,
    ) -> None:
        if not isinstance(mock, bool):
            raise ValueError("mock must be a boolean")
        self.api_key = os.getenv("INTERNS1_API_KEY") if api_key is None else api_key
        self.base_url = os.getenv("INTERNS1_BASE_URL") if base_url is None else base_url
        self.allowed_hosts = (
            frozenset()
            if mock
            else _parse_allowed_api_hosts(os.getenv("INTERNS1_ALLOWED_HOSTS"))
        )
        self.model = (
            os.getenv("INTERNS1_MODEL") or self.DEFAULT_MODEL
            if model is None
            else model
        )
        env_timeout = _positive_int(
            os.getenv("INTERNS1_TIMEOUT"), 60, MAX_TIMEOUT_SECONDS
        )
        env_retries = _positive_int(os.getenv("INTERNS1_MAX_RETRIES"), 2, MAX_RETRIES)
        self.timeout = _strict_positive_int(
            timeout, env_timeout, MAX_TIMEOUT_SECONDS, "timeout"
        )
        self.max_retries = _strict_positive_int(
            max_retries, env_retries, MAX_RETRIES, "max_retries"
        )
        self.mock = mock

    def _build_chat_completions_url(self) -> str:
        if not self.base_url:
            raise ValueError(
                "missing_base_url: INTERNS1_BASE_URL is required in --real mode"
            )
        try:
            parsed = urlsplit(self.base_url)
            port = parsed.port
        except (TypeError, ValueError):
            raise ValueError("invalid_base_url: malformed URL") from None
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "invalid_base_url: HTTPS URL without credentials is required"
            )
        try:
            host = _normalize_api_hostname(parsed.hostname)
        except ValueError:
            raise ValueError("invalid_base_url: hostname is malformed") from None
        if _api_host_is_local_or_literal(host):
            raise ValueError("invalid_base_url: local and literal hosts are forbidden")
        if host not in self.allowed_hosts:
            raise ValueError("disallowed_host: API hostname is not allowlisted")
        if port not in (None, 443):
            raise ValueError(
                "disallowed_origin: real API allowlist authorizes HTTPS port 443 only"
            )
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host + (f":{port}" if port is not None else "")
        normalized = urlunsplit(("https", netloc, parsed.path.rstrip("/"), "", ""))
        return (
            normalized
            if normalized.endswith("/chat/completions")
            else f"{normalized}/chat/completions"
        )

    def _validate_real_mode_config(self) -> None:
        if (
            not isinstance(self.api_key, str)
            or not self.api_key
            or len(self.api_key) > 8_192
        ):
            raise ValueError(
                "missing_api_key: INTERNS1_API_KEY is required in --real mode"
            )
        if (
            not isinstance(self.base_url, str)
            or not self.base_url
            or len(self.base_url) > 2_048
        ):
            raise ValueError(
                "missing_base_url: INTERNS1_BASE_URL is required in --real mode"
            )
        if not self.allowed_hosts:
            raise ValueError(
                "missing_allowed_hosts: INTERNS1_ALLOWED_HOSTS is required in --real mode"
            )
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or len(self.model) > MAX_MODEL_CHARS
        ):
            raise ValueError("invalid_model: model is outside the safe schema")
        self._build_chat_completions_url()

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        top_p: float = 0.9,
        max_tokens: int = 4096,
    ) -> str:
        if (
            not isinstance(messages, list)
            or not 1 <= len(messages) <= MAX_MESSAGES
            or any(
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or not isinstance(message.get("role"), str)
                or message.get("role") not in {"assistant", "system", "user"}
                or not isinstance(message.get("content"), str)
                for message in messages
            )
        ):
            raise ValueError("invalid_request: messages do not match the safe schema")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or not 0.0 <= float(temperature) <= 2.0
            or isinstance(top_p, bool)
            or not isinstance(top_p, (int, float))
            or not math.isfinite(float(top_p))
            or not 0.0 <= float(top_p) <= 1.0
        ):
            raise ValueError(
                "invalid_request: sampling parameters are outside safe ranges"
            )
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= MAX_TOKENS
        ):
            raise ValueError("invalid_request: max_tokens is outside the safe range")
        request_chars = sum(
            len(message["role"]) + len(message["content"]) for message in messages
        )
        if request_chars > MAX_REQUEST_CHARS:
            raise ValueError("invalid_request: messages exceed the size limit")
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or len(self.model) > MAX_MODEL_CHARS
        ):
            raise ValueError("invalid_model: model is outside the safe schema")
        safe_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": safe_messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        encoded_payload = json.dumps(
            payload,
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded_payload) > MAX_REQUEST_CHARS:
            raise ValueError(
                "invalid_request: serialized request exceeds the size limit"
            )
        if self.mock:
            return self.MOCK_RESPONSE
        self._validate_real_mode_config()
        url = self._build_chat_completions_url()
        assert isinstance(self.api_key, str)
        attempts = max(1, self.max_retries)
        deadline = time.monotonic() + min(
            MAX_TOTAL_CHAT_SECONDS, self.timeout * attempts
        )
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("timeout: total request budget exceeded")
            transport = _run_isolated_http(
                {
                    "url": url,
                    "api_key": self.api_key,
                    "payload": payload,
                    "timeout": min(float(self.timeout), remaining),
                },
                min(float(self.timeout), remaining),
            )
            if time.monotonic() > deadline:
                raise ValueError("timeout: total request budget exceeded")
            if transport.get("ok") is not True:
                error = transport.get("error")
                if error == "timeout":
                    if attempt < attempts:
                        continue
                    raise ValueError("timeout: request timed out")
                if error == "network":
                    if attempt < attempts:
                        continue
                    raise ValueError("unknown_error: network request failed")
                if error == "response_too_large":
                    raise ValueError(
                        "invalid_response: response exceeds the size limit"
                    )
                if error == "capacity":
                    raise ValueError(
                        "capacity_error: isolated process capacity is exhausted"
                    )
                if error == "blocked_destination":
                    raise ValueError(
                        "security_error: API destination must resolve only to public "
                        "addresses"
                    )
                raise ValueError("invalid_response: transport rejected the response")
            if set(transport) != {"ok", "status", "body"}:
                raise ValueError("invalid_response: transport response is invalid")
            status = transport.get("status")
            if isinstance(status, bool) or not isinstance(status, int):
                raise ValueError("invalid_response: HTTP status is invalid")
            if status in {401, 403}:
                raise ValueError("auth_error: unauthorized (401/403)")
            if status == 429:
                raise ValueError("rate_limit: HTTP 429")
            if 500 <= status < 600:
                if attempt < attempts:
                    delay = min(0.1, max(0.0, deadline - time.monotonic()))
                    if delay:
                        time.sleep(delay)
                    continue
                raise ValueError(f"server_error: HTTP {status}")
            if status != 200:
                if 300 <= status < 400:
                    raise ValueError("transport_error: redirects are not allowed")
                raise ValueError(f"transport_error: unexpected HTTP {status}")
            encoded_body = transport.get("body")
            if not isinstance(encoded_body, str):
                raise ValueError("invalid_response: response body is invalid")
            try:
                body = base64.b64decode(encoded_body, validate=True)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError(
                        "invalid_response: response exceeds the size limit"
                    )
                data = strict_json_loads(body.decode("utf-8", errors="strict"))
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise TypeError("response content must be text")
            except (KeyError, IndexError, TypeError, UnicodeError, ValueError) as exc:
                if isinstance(exc, ValueError) and str(exc).startswith(
                    "invalid_response: response exceeds"
                ):
                    raise
                raise ValueError(
                    "invalid_response: response JSON is not chat-completions compatible"
                ) from exc
            return content
        raise ValueError("unknown_error: request failed after retries")
