from __future__ import annotations

from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt


class Solver:
    def __init__(self, client: Any, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)

    def _select_prompt_key(self, route_info: dict) -> str:
        solver_name = route_info.get("recommended_solver", "general")
        if solver_name == "program":
            return "program_solver_system"
        if solver_name == "proof":
            return "proof_solver_system"
        if solver_name == "optimization":
            return "solver_system"
        return "solver_system"

    def solve(self, question: str, route_info: dict, plan: dict) -> str:
        if self.mock:
            return (
                "我们按计划求解并完成关键步骤。"
                "最终可得结果为 \\boxed{42}。"
            )

        prompt_key = self._select_prompt_key(route_info)
        template = get_prompt(self.prompts, prompt_key)
        system_prompt = render_prompt(
            template,
            question=question,
            plan=plan,
            route_info=route_info,
        )
        return self.client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\nPlan: {plan}"},
        ])
