from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEY_PATTERNS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "env",
)

_REPLACEMENT = "[REDACTED]"



def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p



def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _sanitize_string(text: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ("inter ns1_api_key".replace(" ", ""), "authorization", "bearer", ".env", "api_key")):
        text = re.sub(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)", rf"\1{_REPLACEMENT}", text)
        text = re.sub(r"(?i)(bearer\s+)([^\s,;]+)", rf"\1{_REPLACEMENT}", text)
        text = re.sub(r"(?i)(inter\w*api\w*key\s*[:=]\s*)([^\s,;]+)", rf"\1{_REPLACEMENT}", text)
        text = re.sub(r"(?i)interns?1_api_key", _REPLACEMENT, text)
        text = re.sub(r"(?i)authorization", _REPLACEMENT, text)
        text = re.sub(r"(?i)bearer", _REPLACEMENT, text)
        text = text.replace(".env", _REPLACEMENT)
    return text



def sanitize_trace(data: Any) -> Any:
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            lk = str(key).lower()
            if any(p in lk for p in _SENSITIVE_KEY_PATTERNS):
                cleaned[key] = _REPLACEMENT
            else:
                cleaned[key] = sanitize_trace(value)
        return cleaned
    if isinstance(data, list):
        return [sanitize_trace(item) for item in data]
    if isinstance(data, str):
        return _sanitize_string(data)
    return data



def safe_json_dump(data: dict[str, Any], path: str | Path) -> bool:
    try:
        out = Path(path)
        ensure_dir(out.parent)
        sanitized = sanitize_trace(data)
        out.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False



def write_trace(trace: dict, trace_dir: str | Path, question_id: str) -> Path:
    trace_path = ensure_dir(trace_dir) / f"{question_id}.json"
    safe_json_dump(trace, trace_path)
    return trace_path
