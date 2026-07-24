from __future__ import annotations

from pathlib import Path
from typing import Any

from math_agent.logging_utils import safe_text_write


def write_markdown_report(
    summary: Any,
    results: list[Any],
    path: Path | str,
) -> None:
    from math_agent.evaluation.shadow_eval import render_markdown_report

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    safe_text_write(render_markdown_report(summary, results), p)
