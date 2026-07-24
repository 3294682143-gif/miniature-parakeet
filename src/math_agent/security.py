from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"

MAX_REDACTION_CONTAINER_ITEMS = 10_000
MAX_SECURITY_TRAVERSAL_NODES = 100_000
_SENSITIVE_KEY_NAMES = {
    ".env",
    "_env",
    "api_key",
    "api_key_value",
    "apikey",
    "authorization",
    "aws_secret_access_key",
    "bearer",
    "client_secret_value",
    "password",
    "passwd",
    "private_key",
    "pwd",
    "secret",
    "secret_access_key",
    "secret_value",
    "token",
}
_SENSITIVE_KEY_SUFFIXES = (
    "_api_key",
    "_api_key_value",
    "_apikey",
    "_authorization",
    "_bearer",
    "_password",
    "_password_value",
    "_passwd",
    "_private_key",
    "_private_key_value",
    "_pwd",
    "_secret",
    "_secret_access_key",
    "_secret_value",
    "_token",
    "_token_value",
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_CREDENTIAL_LABEL = r"""
    (?:
        [A-Z0-9_-]*API[_-]?KEY(?:[_-]VALUE)? |
        [A-Z0-9_-]*(?:PASSWORD|PASSWD|PASSPHRASE|PWD)(?:[_-]VALUE)? |
        [A-Z0-9_-]*PRIVATE[_-]?KEY(?:[_-]VALUE)? |
        [A-Z0-9_-]*SECRET(?:[_-](?:ACCESS[_-]?KEY|VALUE))? |
        [A-Z0-9_-]*TOKEN
    )
"""
_CREDENTIAL_ASSIGNMENT = re.compile(
    rf"""
    (?P<prefix>
        ["']?
        {_CREDENTIAL_LABEL}
        ["']?\s*[:=]\s*["']?
    )
    (?!\[REDACTED\])
    [^\s"',;}}\]]+
    """,
    re.IGNORECASE | re.VERBOSE,
)
_QUOTED_CREDENTIAL_ASSIGNMENT = re.compile(
    rf"""
    (?P<prefix>
        ["']?
        {_CREDENTIAL_LABEL}
        ["']?\s*[:=]\s*
    )
    (?P<quote>["'])
    (?!\[REDACTED\])
    .*?
    (?P=quote)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_AUTHORIZATION_VALUE = re.compile(
    r"(?P<prefix>\bAuthorization[\"']?\s*[:=]\s*[\"']?)"
    r"(?:(?:Basic|Bearer|Token)\s+)?(?!\[REDACTED\])[^\s\"',;}]+",
    re.IGNORECASE,
)
_URI_USERINFO = re.compile(
    r"(?P<scheme>\b[A-Z][A-Z0-9+.-]*://)" r"(?!\[REDACTED\]@)[^\s/@:]+:[^\s/@]+@",
    re.IGNORECASE,
)
_TOKEN_PATTERNS = (
    re.compile(r"\bBearer\s+(?!\[REDACTED\])[A-Za-z0-9._~+/-]{10,}\b", re.I),
    re.compile(r"\bBasic\s+(?!\[REDACTED\])[A-Za-z0-9+/]{12,}={0,2}\b", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bxapp-[A-Za-z0-9-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{16,}\b", re.IGNORECASE),
    re.compile(r"\bdop_v1_[A-Za-z0-9]{40,}\b", re.IGNORECASE),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://" r"[^\s:/]+:[^\s@/]+@",
        re.IGNORECASE,
    ),
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", re.IGNORECASE),
)
_BARE_SHA256_HEX = re.compile(r"(?<![A-Za-z0-9])[A-Fa-f0-9]{64}(?![A-Za-z0-9])")
_OPAQUE_TOKEN_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z0-9_+~=-]{32,}(?![A-Za-z0-9_])"
)


def _redact_opaque_token_candidate(match: re.Match[str]) -> str:
    """Redact unlabeled random-looking credential candidates."""

    value = match.group(0)
    has_lower = any(character.islower() for character in value)
    has_upper = any(character.isupper() for character in value)
    has_digit = any(character.isdigit() for character in value)
    counts: dict[str, int] = {}
    for character in value:
        counts[character] = counts.get(character, 0) + 1
    entropy = -sum(
        (count / len(value)) * math.log2(count / len(value))
        for count in counts.values()
    )
    mixed_case_candidate = has_lower and has_upper and has_digit
    base52_candidate = len(value) >= 40 and has_lower and has_upper and not has_digit
    lowercase_candidate = len(value) >= 40 and has_lower and not has_upper
    uppercase_candidate = len(value) >= 40 and has_upper and not has_lower
    if (mixed_case_candidate and entropy >= 3.5) or (
        (base52_candidate or lowercase_candidate or uppercase_candidate)
        and entropy >= 3.8
    ):
        return REDACTED
    return value


def redact_sensitive_text(text: str) -> str:
    """Redact common credential forms without requiring a nearby label."""

    redacted = _PRIVATE_KEY_BLOCK.sub(REDACTED, text)
    redacted = _AUTHORIZATION_VALUE.sub(rf"\g<prefix>{REDACTED}", redacted)
    redacted = _URI_USERINFO.sub(rf"\g<scheme>{REDACTED}@", redacted)
    redacted = _QUOTED_CREDENTIAL_ASSIGNMENT.sub(
        rf"\g<prefix>\g<quote>{REDACTED}\g<quote>", redacted
    )
    redacted = _CREDENTIAL_ASSIGNMENT.sub(rf"\g<prefix>{REDACTED}", redacted)
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    redacted = _BARE_SHA256_HEX.sub(REDACTED, redacted)
    redacted = _OPAQUE_TOKEN_CANDIDATE.sub(_redact_opaque_token_candidate, redacted)
    return redacted


def safe_exception_text(exc: BaseException, limit: int = 1_000) -> str:
    """Render an exception without trusting its string implementation."""

    try:
        message = str(exc)
    except BaseException:
        message = "message unavailable"
    try:
        message = redact_sensitive_text(message)
    except BaseException:
        message = "message unavailable"
    if len(message) > limit:
        return f"{message[:limit]}...[truncated]"
    return message


def is_sensitive_key(key: str) -> bool:
    """Return whether a mapping key conventionally carries credential material."""

    normalized = re.sub(r"[\s.-]+", "_", key.strip().lower())
    return normalized in _SENSITIVE_KEY_NAMES or normalized.endswith(
        _SENSITIVE_KEY_SUFFIXES
    )


def _is_sensitive_key(key: str) -> bool:
    """Backward-compatible private alias for older callers."""

    return is_sensitive_key(key)


def path_has_link_component(path: str | Path) -> bool:
    """Fail closed when an existing path component is a symlink or junction."""

    try:
        candidate = Path(path).absolute()
    except (OSError, RuntimeError, TypeError, ValueError):
        return True
    for component in (candidate, *candidate.parents):
        try:
            if (
                component.is_symlink()
                or getattr(component, "is_junction", lambda: False)()
            ):
                return True
        except OSError:
            return True
    return False


def contains_non_finite_number(
    data: Any,
    *,
    _depth: int = 0,
    _seen: set[int] | None = None,
    _budget: list[int] | None = None,
) -> bool:
    """Detect NaN and infinities in bounded JSON/YAML-like containers."""

    budget = _budget if _budget is not None else [MAX_SECURITY_TRAVERSAL_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        return True
    if isinstance(data, float):
        try:
            return not math.isfinite(data)
        except (TypeError, ValueError):
            return True
    if _depth > 32:
        return True
    if not isinstance(data, (dict, list, tuple, set, frozenset)):
        return False

    seen = _seen if _seen is not None else set()
    identity = id(data)
    if identity in seen:
        return False
    seen.add(identity)
    try:
        values = data.items() if isinstance(data, dict) else data
        for index, item in enumerate(values):
            if index >= MAX_REDACTION_CONTAINER_ITEMS:
                return True
            if isinstance(data, dict):
                key, value = item
                if contains_non_finite_number(
                    key, _depth=_depth + 1, _seen=seen, _budget=budget
                ):
                    return True
            else:
                value = item
            if contains_non_finite_number(
                value, _depth=_depth + 1, _seen=seen, _budget=budget
            ):
                return True
    except BaseException:
        return True
    return False


def redact_sensitive_data(
    data: Any,
    *,
    _depth: int = 0,
    _seen: set[int] | None = None,
    _budget: list[int] | None = None,
) -> Any:
    """Recursively redact sensitive keys and credential-shaped string values."""

    budget = _budget if _budget is not None else [MAX_SECURITY_TRAVERSAL_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        return REDACTED
    if _depth > 32:
        return REDACTED
    if isinstance(data, str):
        return redact_sensitive_text(data)
    if isinstance(data, (bytes, bytearray, memoryview)):
        return REDACTED
    if data is None or isinstance(data, (bool, int)):
        return data
    if isinstance(data, float):
        return data if math.isfinite(data) else REDACTED
    if not isinstance(data, (dict, list, tuple, set, frozenset)):
        return REDACTED

    seen = _seen if _seen is not None else set()
    identity = id(data)
    if identity in seen:
        return REDACTED
    seen.add(identity)
    if isinstance(data, dict):
        cleaned: dict[Any, Any] = {}
        try:
            for index, (key, value) in enumerate(data.items()):
                if index >= MAX_REDACTION_CONTAINER_ITEMS:
                    cleaned["[TRUNCATED]"] = REDACTED
                    break
                try:
                    key_text = key if isinstance(key, str) else str(key)
                except BaseException:
                    key_text = REDACTED
                    value = REDACTED
                redacted_key_text = redact_sensitive_text(key_text)
                safe_key = redacted_key_text
                if safe_key in cleaned:
                    safe_key = f"{redacted_key_text}#{index + 1}"
                if is_sensitive_key(key_text):
                    cleaned[safe_key] = REDACTED
                else:
                    cleaned[safe_key] = redact_sensitive_data(
                        value,
                        _depth=_depth + 1,
                        _seen=seen,
                        _budget=budget,
                    )
        except BaseException:
            return REDACTED
        return cleaned
    cleaned_items: list[Any] = []
    try:
        for index, item in enumerate(data):
            if index >= MAX_REDACTION_CONTAINER_ITEMS:
                cleaned_items.append(REDACTED)
                break
            cleaned_items.append(
                redact_sensitive_data(
                    item,
                    _depth=_depth + 1,
                    _seen=seen,
                    _budget=budget,
                )
            )
    except BaseException:
        return REDACTED
    return tuple(cleaned_items) if isinstance(data, tuple) else cleaned_items
