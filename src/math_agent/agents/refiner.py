from __future__ import annotations

from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt


class Refiner:
    def __init__(
        self,
        client: Any,
        prompt_config_path: str | Path = "configs/prompts.yaml",
        mock: bool = True,
        max_iterations: int = 3,
    ) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)
        self.max_iterations = max_iterations
        self._iteration_count = 0
        self._last_solution = ""

    def refine(
        self, question: str, draft_solution: str, verification_feedback: dict | str
    ) -> str:
        if self.mock:
            return draft_solution

        if self._iteration_count >= self.max_iterations:
            return draft_solution

        self._iteration_count += 1

        try:
            template = get_prompt(self.prompts, "refiner_system")
            system_prompt = render_prompt(
                template,
                question=question,
                draft_solution=draft_solution,
                route_info=verification_feedback,
            )
            refined = self.client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Please refine the solution."},
                ]
            )
            if refined == self._last_solution:
                return refined
            self._last_solution = refined
            return refined
        except Exception:
            return draft_solution


def run(draft_solution: str) -> str:
    return draft_solution
