from __future__ import annotations

from pathlib import Path
from string import Formatter

import yaml


def load_prompts(path: str | Path) -> dict:
    """Load prompt templates from a YAML file."""
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt config file not found: {prompt_path}")

    try:
        data = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in prompt config {prompt_path}: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TypeError(
            f"Prompt config must be a mapping/dict, got {type(data).__name__} in {prompt_path}"
        )
    return data


def get_prompt(prompts: dict, key: str) -> str:
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
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }
    missing = sorted(field for field in needed_fields if field not in kwargs)
    if missing:
        raise KeyError(
            "Missing variables for prompt rendering: " + ", ".join(missing)
        )

    try:
        return template.format(**kwargs)
    except KeyError as exc:
        missing_var = exc.args[0]
        raise KeyError(f"Missing variable for prompt rendering: {missing_var}") from exc
