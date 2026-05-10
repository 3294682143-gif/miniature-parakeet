from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
_REDACTED = "***REDACTED***"
_SENSITIVE_KEYWORDS = ("api_key", "apikey", "secret", "token", "password")


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO)
    return logging.getLogger(name)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lower_key = str(key).lower()
            if any(word in lower_key for word in _SENSITIVE_KEYWORDS):
                cleaned[key] = _REDACTED
            else:
                cleaned[key] = _sanitize_value(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        if "INTERNS1_API_KEY" in value or ".env" in value:
            return value.replace("INTERNS1_API_KEY", _REDACTED).replace(".env", _REDACTED)
        return value
    return value


def sanitize_trace(data: dict[str, Any]) -> dict[str, Any]:
    return _sanitize_value(data)


def safe_json_dump(data: dict[str, Any], path: str | Path) -> Path:
    out_path = Path(path)
    ensure_dir(out_path.parent)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_trace(trace: dict, trace_dir: str | Path, question_id: str) -> Path | None:
    try:
        cleaned = sanitize_trace(trace)
        target_dir = ensure_dir(trace_dir)
        safe_qid = str(question_id or "unknown").replace("/", "_")
        return safe_json_dump(cleaned, target_dir / f"{safe_qid}.json")
    except Exception:
        LOGGER.exception("Failed to write trace for question_id=%s", question_id)
        return None
