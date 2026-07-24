from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .security import (
    path_has_link_component,
    redact_sensitive_data,
    redact_sensitive_text,
)

_SAFE_TRACE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_LOWERCASE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TRUSTED_TRACE_HASH_PATHS = frozenset(
    {
        ("execution_fingerprint",),
        ("final_result", "execution_fingerprint"),
        ("final_result", "input_fingerprint"),
        ("input_fingerprint",),
        ("execution_profile", "endpoint_sha256"),
        ("execution_profile", "prompt_config_sha256"),
        ("execution_profile", "trace_dir_sha256"),
    }
)
_TRUSTED_STRUCTURED_ARTIFACT_KEYS = {
    "config_snapshot.json": frozenset(
        {
            "created_at",
            "enable_tools",
            "hard_mode",
            "hard_mode_level",
            "input_manifest_sha256",
            "input_path",
            "limit",
            "mock",
            "mode",
            "out_dir",
            "real",
            "results_name",
            "run_id",
            "save_trace",
            "trace_dir",
        }
    ),
    "dry_run_summary.json": frozenset(
        {
            "average_latency_ms",
            "fail_count",
            "input_manifest_sha256",
            "invalid_count",
            "json_valid_count",
            "missing_final_count",
            "official_warning",
            "report_path",
            "results_path",
            "run_id",
            "success_count",
            "total",
            "trace_dir",
        }
    ),
    "run_record.json": frozenset(
        {
            "command",
            "created_at",
            "elapsed_ms",
            "errors",
            "input_manifest_sha256",
            "invalid_count",
            "result_count",
            "run_id",
            "trace_dir",
        }
    ),
}
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
MAX_SAFE_JSON_BYTES = 8 * 1024 * 1024
MAX_SAFE_TEXT_BYTES = 64 * 1024 * 1024
_TEXT_SIZE_CHUNK_CHARS = 1024 * 1024


def ensure_dir(path: str | Path) -> Path:
    p = Path(path).absolute()
    if path_has_link_component(p):
        raise OSError("output directory contains a link or junction")
    p.mkdir(parents=True, exist_ok=True)
    if path_has_link_component(p) or not p.is_dir():
        raise OSError("output directory is not a safe directory")
    return p


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_trace(data: Any) -> Any:
    return redact_sensitive_data(data)


def _safe_trace_filename(question_id: str) -> str:
    raw_id = str(question_id)
    contains_secret = redact_sensitive_text(raw_id) != raw_id
    normalized_name = raw_id.casefold().split(".", 1)[0]
    if (
        not contains_secret
        and _SAFE_TRACE_ID.fullmatch(raw_id)
        and raw_id == raw_id.casefold()
        and normalized_name not in _WINDOWS_RESERVED_NAMES
        and not raw_id.endswith((".", " "))
    ):
        return f"{raw_id}.json"

    digest = sha256(raw_id.encode("utf-8", errors="surrogatepass")).hexdigest()
    # ``~`` is deliberately outside _SAFE_TRACE_ID, so a caller-controlled ID can
    # never alias the hashed namespace. Hashing all mixed/upper-case IDs also avoids
    # silent Q1/q1 overwrites on case-insensitive filesystems.
    return f"~trace-{digest}.json"


def trace_path_for_question(trace_dir: str | Path, question_id: str) -> Path:
    root = Path(trace_dir).absolute()
    if path_has_link_component(root):
        raise ValueError("trace directory contains a link or junction")
    filename = _safe_trace_filename(question_id)
    candidate = root / filename
    if not filename.startswith("~trace-") and candidate.exists():
        try:
            # Windows resolves an existing case-insensitive alias to the actual
            # on-disk spelling in O(1); avoid an O(N) directory scan per trace.
            if candidate.resolve(strict=True).name != filename:
                digest = sha256(
                    str(question_id).encode("utf-8", errors="surrogatepass")
                ).hexdigest()
                filename = f"~trace-{digest}.json"
        except OSError as exc:
            raise ValueError("trace path is unreadable") from exc
    return root / filename


def _sanitize_structured_output(
    data: dict[str, Any],
    *,
    trusted_hash_paths: frozenset[tuple[str, ...]] = frozenset(),
) -> Any:
    sanitized = sanitize_trace(data)
    if not isinstance(sanitized, dict):
        return sanitized
    for field_path in trusted_hash_paths:
        original_parent: Any = data
        sanitized_parent: Any = sanitized
        for field in field_path[:-1]:
            if not isinstance(original_parent, dict) or not isinstance(
                sanitized_parent, dict
            ):
                break
            original_parent = original_parent.get(field)
            sanitized_parent = sanitized_parent.get(field)
        else:
            leaf = field_path[-1]
            if not isinstance(original_parent, dict) or not isinstance(
                sanitized_parent, dict
            ):
                continue
            value = original_parent.get(leaf)
            if isinstance(value, str) and _LOWERCASE_SHA256.fullmatch(value):
                sanitized_parent[leaf] = value
    return sanitized


def sanitize_trusted_trace_payload(data: dict[str, Any]) -> Any:
    """Sanitize a program-constructed trace while retaining exact hash paths."""

    return _sanitize_structured_output(
        data, trusted_hash_paths=_TRUSTED_TRACE_HASH_PATHS
    )


def _write_sanitized_json(sanitized: Any, path: str | Path) -> bool:
    try:
        rendered = json.dumps(sanitized, ensure_ascii=False, indent=2, allow_nan=False)
        if len(rendered.encode("utf-8")) > MAX_SAFE_JSON_BYTES:
            return False
        # The structured payload has already been recursively sanitized. Writing
        # it through safe_text_write() would run the context-free text redactor a
        # second time and erase explicitly named provenance hashes.
        _atomic_text_write(rendered, path)
        return True
    except Exception:
        return False


def safe_json_dump(data: dict[str, Any], path: str | Path) -> bool:
    try:
        sanitized = sanitize_trace(data)
    except Exception:
        return False
    return _write_sanitized_json(sanitized, path)


def _atomic_text_write(text: str, path: str | Path) -> None:
    raw_text = str(text)
    if len(raw_text) > MAX_SAFE_TEXT_BYTES:
        raise ValueError("text output exceeds the safe size limit")
    byte_count = 0
    for offset in range(0, len(raw_text), _TEXT_SIZE_CHUNK_CHARS):
        byte_count += len(
            raw_text[offset : offset + _TEXT_SIZE_CHUNK_CHARS].encode("utf-8")
        )
        if byte_count > MAX_SAFE_TEXT_BYTES:
            raise ValueError("text output exceeds the safe size limit")
    out = Path(path).absolute()
    ensure_dir(out.parent)
    if path_has_link_component(out):
        raise OSError("output path contains a link or junction")
    temporary = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(raw_text)
            handle.flush()
            os.fsync(handle.fileno())
        if path_has_link_component(out):
            raise OSError("output path changed before replacement")
        os.replace(temporary, out)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def write_trusted_structured_artifact(data: dict[str, Any], path: str | Path) -> None:
    """Write one exact program-owned artifact schema with its manifest hash intact."""

    expected_keys = _TRUSTED_STRUCTURED_ARTIFACT_KEYS.get(Path(path).name)
    if expected_keys is None:
        raise ValueError("unsupported trusted structured artifact")
    if frozenset(data) != expected_keys:
        raise ValueError("trusted structured artifact schema mismatch")
    sanitized = _sanitize_structured_output(
        data, trusted_hash_paths=frozenset({("input_manifest_sha256",)})
    )
    if not _write_sanitized_json(sanitized, path):
        raise OSError("trusted structured artifact write failed")


def safe_text_write(text: str, path: str | Path) -> None:
    """Redact and atomically replace a text sink without following leaf links."""

    raw_text = str(text)
    if len(raw_text) > MAX_SAFE_TEXT_BYTES:
        raise ValueError("text output exceeds the safe size limit")
    _atomic_text_write(redact_sensitive_text(raw_text), path)


def atomic_text_write(text: str, path: str | Path) -> None:
    """Atomically preserve caller-validated protocol/data text exactly."""

    _atomic_text_write(text, path)


def write_trace(trace: dict, trace_dir: str | Path, question_id: str) -> Path:
    trace_root = ensure_dir(trace_dir)
    trace_path = trace_path_for_question(trace_root, question_id)
    try:
        sanitized = sanitize_trusted_trace_payload(trace)
    except Exception:
        sanitized = None
    if sanitized is None or not _write_sanitized_json(sanitized, trace_path):
        raise OSError("trace write failed")
    return trace_path
