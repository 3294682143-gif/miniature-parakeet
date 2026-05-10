from __future__ import annotations

from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt


class Planner:
    def __init__(self, client: Any, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)

    def plan(self, question: str, route_info: dict) -> dict:
        if self.mock:
            return {
                "problem_parse": {
                    "goal": f"Solve: {question}",
                    "givens": [question],
                    "symbols": route_info.get("symbols", []),
                },
                "solution_plan": [
                    "Parse the mathematical objective and constraints.",
                    "Choose a method based on the routed solver type.",
                    "Execute derivation and prepare a boxed final answer.",
                ],
                "potential_tools": ["python", "sympy"],
                "risk_points": [
                    "Arithmetic or algebraic sign errors.",
                    "Missing edge-case constraints from the question.",
                ],
            }

        template = get_prompt(self.prompts, "planner_system")
        system_prompt = render_prompt(template, question=question)
        user_prompt = f"Route info: {route_info}\nReturn JSON with keys: problem_parse, solution_plan, potential_tools, risk_points."
        reply = self.client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        return {
            "problem_parse": {"goal": question, "givens": [question], "symbols": []},
            "solution_plan": ["Model-generated plan."],
            "potential_tools": ["none"],
            "risk_points": [f"Unparsed planner response: {reply[:100]}"],
        }



def run(question: str) -> str:
    """Compatibility helper used by pipeline tests and mock pipeline."""
    return f"Plan for: {question}"
