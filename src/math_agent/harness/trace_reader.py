from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from math_agent.io_utils import NonFiniteJSONError, strict_json_loads
from math_agent.logging_utils import sanitize_trusted_trace_payload
from math_agent.security import (
    contains_non_finite_number,
    path_has_link_component,
    redact_sensitive_data,
    redact_sensitive_text,
)

MAX_TRACE_FILE_BYTES = 8 * 1024 * 1024
MAX_TRACE_FILES = 10_000
MAX_TRACE_DIR_ENTRIES = 20_000
MAX_TRACE_DIR_BYTES = 64 * 1024 * 1024


def _mask_sensitive(value: Any) -> Any:
    return redact_sensitive_data(value)


def _safe_path_label(path: Path) -> str:
    raw = str(path)
    return raw if redact_sensitive_text(raw) == raw else "[redacted-path]"


def _failure(
    path: Path,
    code: str,
    message: str,
    *,
    file_bytes: int | None = None,
    **details: Any,
) -> dict[str, Any]:
    return {
        "ok": False,
        "path": _safe_path_label(path),
        "file_bytes": file_bytes,
        "error": {"code": code, "message": message, **details},
        "trace": None,
    }


def _read_trace(
    path: str | Path,
    *,
    sanitizer: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    trace_path = Path(path)
    if path_has_link_component(trace_path):
        return _failure(
            trace_path, "unsupported_trace_file", "trace links are not allowed"
        )
    try:
        path_stat = os.lstat(trace_path)
    except FileNotFoundError:
        return _failure(trace_path, "file_not_found", "trace file not found")
    except OSError:
        return _failure(trace_path, "read_error", "trace metadata could not be read")
    if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
        return _failure(
            trace_path,
            "unsupported_trace_file",
            "trace must be a single-link regular file",
        )
    if path_stat.st_size > MAX_TRACE_FILE_BYTES:
        return _failure(trace_path, "trace_too_large", "trace exceeds size limit")

    descriptor: int | None = None
    verified_file_bytes: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(trace_path, flags)
        descriptor_stat = os.fstat(descriptor)
        current_path_stat = os.lstat(trace_path)
        if (
            path_has_link_component(trace_path)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or descriptor_stat.st_nlink != 1
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (current_path_stat.st_dev, current_path_stat.st_ino)
            or descriptor_stat.st_size != current_path_stat.st_size
            or descriptor_stat.st_size > MAX_TRACE_FILE_BYTES
        ):
            return _failure(
                trace_path, "unsupported_trace_file", "trace identity is unsafe"
            )

        payload = bytearray()
        while len(payload) <= MAX_TRACE_FILE_BYTES:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAX_TRACE_FILE_BYTES + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)

        post_descriptor_stat = os.fstat(descriptor)
        post_path_stat = os.lstat(trace_path)
        if path_has_link_component(trace_path):
            return _failure(
                trace_path, "unsupported_trace_file", "trace links are not allowed"
            )
        if (
            len(payload) > MAX_TRACE_FILE_BYTES
            or post_descriptor_stat.st_size > MAX_TRACE_FILE_BYTES
            or post_path_stat.st_size > MAX_TRACE_FILE_BYTES
        ):
            return _failure(trace_path, "trace_too_large", "trace exceeds size limit")
        expected_identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
        if (
            not stat.S_ISREG(post_descriptor_stat.st_mode)
            or post_descriptor_stat.st_nlink != 1
            or expected_identity
            != (post_descriptor_stat.st_dev, post_descriptor_stat.st_ino)
            or expected_identity != (post_path_stat.st_dev, post_path_stat.st_ino)
            or post_descriptor_stat.st_size != len(payload)
            or post_path_stat.st_size != len(payload)
        ):
            return _failure(
                trace_path,
                "unsupported_trace_file",
                "trace identity changed during read",
            )
        verified_file_bytes = len(payload)
        raw = strict_json_loads(bytes(payload).decode("utf-8", errors="strict"))
    except NonFiniteJSONError:
        return _failure(
            trace_path,
            "invalid_trace_value",
            "trace contains a non-finite number",
            file_bytes=verified_file_bytes,
        )
    except json.JSONDecodeError as exc:
        return _failure(
            trace_path,
            "bad_json",
            "invalid trace json",
            file_bytes=verified_file_bytes,
            line=exc.lineno,
            column=exc.colno,
        )
    except (RecursionError, ValueError):
        return _failure(
            trace_path,
            "bad_json",
            "invalid trace json",
            file_bytes=verified_file_bytes,
        )
    except (OSError, UnicodeError):
        return _failure(
            trace_path,
            "read_error",
            "trace could not be read",
            file_bytes=verified_file_bytes,
        )
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass

    if contains_non_finite_number(raw):
        return _failure(
            trace_path,
            "invalid_trace_value",
            "trace contains a non-finite number",
            file_bytes=verified_file_bytes,
        )
    if not isinstance(raw, dict):
        return _failure(
            trace_path,
            "invalid_trace_root",
            "trace root must be a JSON object",
            file_bytes=verified_file_bytes,
        )

    return {
        "ok": True,
        "path": _safe_path_label(trace_path),
        "file_bytes": len(payload),
        "error": None,
        "trace": sanitizer(raw),
    }


def read_trace(path: str | Path) -> dict[str, Any]:
    """Read an untrusted replay trace with context-free redaction."""

    return _read_trace(path, sanitizer=_mask_sensitive)


def read_trusted_program_trace(path: str | Path) -> dict[str, Any]:
    """Read a program-owned trace while retaining exact provenance hash paths."""

    return _read_trace(path, sanitizer=sanitize_trusted_trace_payload)


def read_trace_dir(trace_dir: str | Path) -> dict[str, Any]:
    root = Path(trace_dir)
    safe_root = _safe_path_label(root)
    if path_has_link_component(root) or not root.exists() or not root.is_dir():
        return {
            "ok": False,
            "trace_dir": safe_root,
            "error": {
                "code": "dir_not_found",
                "message": "trace directory not found or unsafe",
            },
            "items": [],
        }

    try:
        candidates: list[Path] = []
        entry_count = 0
        for path in root.iterdir():
            entry_count += 1
            if entry_count > MAX_TRACE_DIR_ENTRIES:
                return {
                    "ok": False,
                    "trace_dir": safe_root,
                    "error": {
                        "code": "too_many_trace_entries",
                        "message": "trace directory exceeds total-entry limit",
                    },
                    "items": [],
                }
            if not path.name.lower().endswith(".json"):
                continue
            candidates.append(path)
            if len(candidates) > MAX_TRACE_FILES:
                return {
                    "ok": False,
                    "trace_dir": safe_root,
                    "error": {
                        "code": "too_many_trace_files",
                        "message": "trace directory exceeds file-count limit",
                    },
                    "items": [],
                }
    except OSError:
        return {
            "ok": False,
            "trace_dir": safe_root,
            "error": {
                "code": "dir_read_error",
                "message": "trace directory unreadable",
            },
            "items": [],
        }
    if path_has_link_component(root):
        return {
            "ok": False,
            "trace_dir": safe_root,
            "error": {
                "code": "dir_not_found",
                "message": "trace directory not found or unsafe",
            },
            "items": [],
        }
    candidates.sort(key=lambda path: path.name.casefold())
    if path_has_link_component(root):
        return {
            "ok": False,
            "trace_dir": safe_root,
            "error": {
                "code": "dir_not_found",
                "message": "trace directory not found or unsafe",
            },
            "items": [],
        }

    items: list[dict[str, Any]] = []
    verified_total_bytes = 0
    for candidate in candidates:
        item = read_trace(candidate)
        file_bytes = item.get("file_bytes")
        if file_bytes is not None:
            if (
                isinstance(file_bytes, bool)
                or not isinstance(file_bytes, int)
                or file_bytes < 0
            ):
                return {
                    "ok": False,
                    "trace_dir": safe_root,
                    "error": {
                        "code": "trace_metadata_unreadable",
                        "message": "verified trace metadata is unavailable",
                    },
                    "items": [],
                }
            verified_total_bytes += file_bytes
            if verified_total_bytes > MAX_TRACE_DIR_BYTES:
                return {
                    "ok": False,
                    "trace_dir": safe_root,
                    "error": {
                        "code": "trace_directory_too_large",
                        "message": "trace directory exceeds byte limit",
                    },
                    "items": [],
                }
        elif item.get("ok") is True:
            return {
                "ok": False,
                "trace_dir": safe_root,
                "error": {
                    "code": "trace_metadata_unreadable",
                    "message": "verified trace metadata is unavailable",
                },
                "items": [],
            }
        items.append(item)
    ok_count = sum(1 for item in items if item["ok"])
    return {
        "ok": True,
        "trace_dir": safe_root,
        "error": None,
        "items": items,
        "total": len(items),
        "ok_count": ok_count,
        "error_count": len(items) - ok_count,
    }
