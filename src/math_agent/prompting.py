from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from string import Formatter
from types import MappingProxyType
from typing import Any

import yaml  # type: ignore[import-untyped]

from .security import safe_exception_text

MAX_PROMPT_CONFIG_BYTES = 1 * 1024 * 1024


def _resolve_prompt_path(path: str | Path) -> Path:
    prompt_path = Path(path)
    if prompt_path.exists():
        return prompt_path
    if str(path).replace("\\", "/") == "configs/prompts.yaml":
        installed_path = (
            Path(__file__).resolve().parents[1] / "configs" / "prompts.yaml"
        )
        if installed_path.is_file():
            return installed_path
    return prompt_path


def _read_prompt_config_bytes(path: str | Path) -> tuple[Path, bytes]:
    prompt_path = _resolve_prompt_path(path)
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt config file not found: {prompt_path}")
    try:
        size = prompt_path.stat().st_size
        if size <= 0 or size > MAX_PROMPT_CONFIG_BYTES:
            raise ValueError("Prompt config file is empty or exceeds the size limit")
        raw = prompt_path.read_bytes()
    except OSError as exc:
        raise ValueError("Prompt config file is unreadable") from exc
    if len(raw) != size:
        raise ValueError("Prompt config file changed while it was being read")
    return prompt_path, raw


def prompt_config_fingerprint(path: str | Path) -> str:
    _, raw = _read_prompt_config_bytes(path)
    return sha256(raw).hexdigest()


def _parse_prompt_config(prompt_path: Path, raw: bytes) -> dict:
    try:
        data = yaml.safe_load(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(
            f"Invalid YAML in prompt config {prompt_path}: {safe_exception_text(exc)}"
        ) from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError(
            f"Prompt config must be a mapping/dict, got {type(data).__name__} in {prompt_path}"
        )
    return data


def load_prompts_snapshot(path: str | Path) -> tuple[dict, str]:
    """Parse prompts and hash the exact same immutable byte snapshot."""

    prompt_path, raw = _read_prompt_config_bytes(path)
    return _parse_prompt_config(prompt_path, raw), sha256(raw).hexdigest()


def load_prompts(path: str | Path) -> dict:
    """Load prompt templates from a YAML file."""

    prompts, _ = load_prompts_snapshot(path)
    return prompts


def freeze_prompts(prompts: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an isolated, read-only prompt snapshot."""

    return MappingProxyType(deepcopy(dict(prompts)))


def get_prompt(prompts: Mapping[str, Any], key: str) -> str:
    """Get one prompt template by key and validate non-empty content."""
    if key not in prompts:
        raise KeyError(f"Prompt key not found: '{key}'")

    value = prompts[key]
    if not isinstance(value, str):
        raise TypeError(f"Prompt '{key}' must be a string, got {type(value).__name__}")

    if not value.strip():
        raise ValueError(f"Prompt '{key}' is empty")

    return value


def render_prompt(template: str, **kwargs) -> str:
    """Render one prompt template with explicit missing-variable errors."""
    if not isinstance(template, str):
        raise TypeError(f"template must be a string, got {type(template).__name__}")

    needed_fields = {
        field_name for _, field_name, _, _ in Formatter().parse(template) if field_name
    }
    missing = sorted(field for field in needed_fields if field not in kwargs)
    if missing:
        raise KeyError("Missing variables for prompt rendering: " + ", ".join(missing))

    try:
        return template.format(**kwargs)
    except KeyError as exc:
        missing_var = exc.args[0]
        raise KeyError(f"Missing variable for prompt rendering: {missing_var}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to render prompt template: {exc}") from exc
