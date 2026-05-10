from __future__ import annotations

from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt


class Explainer:
    def __init__(self, client: Any, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)

    def explain(self, question: str, final_solution: str, final_answer: str) -> str:
        if self.mock:
            return "提示：先识别题目目标，再按步骤推导并检查最终答案是否满足条件。"

        try:
            template = get_prompt(self.prompts, "explainer_system")
            system_prompt = render_prompt(template, question=question, final_answer=final_answer)
            return self.client.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Final solution: {final_solution}"},
            ])
        except Exception:
            return "提示：请回顾关键等式变形，并代回原题检查答案。"


def run(question: str) -> str:
    return "提示：先识别题目目标，再按步骤推导并检查最终答案是否满足条件。"
