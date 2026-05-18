from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "token",
    "secret",
    "password",
    "access_token",
    "refresh_token",
}


def _mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k).lower()
            if any(s in key for s in _SENSITIVE_KEYS):
                out[k] = "[REDACTED]"
            else:
                out[k] = _mask_sensitive(v)
        return out
    if isinstance(value, list):
        return [_mask_sensitive(v) for v in value]
    if isinstance(value, str):
        lowered = value.lower()
        if "bearer " in lowered or "sk-" in value or "api_key" in lowered:
            return "[REDACTED]"
    return value


def read_trace(path: str | Path) -> dict[str, Any]:
    trace_path = Path(path)
    if not trace_path.exists():
        return {"ok": False, "path": str(trace_path), "error": {"code": "file_not_found", "message": f"trace file not found: {trace_path}"}, "trace": None}
    try:
        raw = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "path": str(trace_path),
            "error": {"code": "bad_json", "message": f"invalid json: {exc.msg}", "line": exc.lineno, "column": exc.colno},
            "trace": None,
        }
    except Exception as exc:
        return {"ok": False, "path": str(trace_path), "error": {"code": "read_error", "message": str(exc)}, "trace": None}

    return {"ok": True, "path": str(trace_path), "error": None, "trace": _mask_sensitive(raw)}


def read_trace_dir(trace_dir: str | Path) -> dict[str, Any]:
    root = Path(trace_dir)
    if not root.exists() or not root.is_dir():
        return {"ok": False, "trace_dir": str(root), "error": {"code": "dir_not_found", "message": f"trace dir not found: {root}"}, "items": []}

    items = [read_trace(p) for p in sorted(root.glob("*.json"))]
    ok_count = sum(1 for item in items if item["ok"])
    return {"ok": True, "trace_dir": str(root), "error": None, "items": items, "total": len(items), "ok_count": ok_count, "error_count": len(items) - ok_count}
