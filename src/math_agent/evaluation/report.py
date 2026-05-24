from __future__ import annotations

from pathlib import Path

from math_agent.evaluation.shadow_eval import ShadowEvalResult, ShadowEvalSummary, render_markdown_report


def write_markdown_report(
    summary: ShadowEvalSummary,
    results: list[ShadowEvalResult],
    path: Path | str,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_markdown_report(summary, results), encoding="utf-8")
