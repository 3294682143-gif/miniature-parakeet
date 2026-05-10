from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt


def _fallback_plan(question: str, route_info: dict) -> dict:
    return {
        "problem_parse": {
            "goal": f"Solve: {question}",
            "givens": [question],
            "symbols": route_info.get("symbols", []),
        },
        "solution_plan": [
            "Parse objective and constraints.",
            "Select method and derive result.",
            "Check answer and produce final output.",
        ],
        "potential_tools": ["python", "sympy"],
        "risk_points": ["Parse ambiguity or arithmetic mistakes."],
    }


class Planner:
    def __init__(self, client: Any, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)

    def plan(self, question: str, route_info: dict) -> dict:
        if self.mock:
            return _fallback_plan(question, route_info)

        template = get_prompt(self.prompts, "planner_system")
        system_prompt = render_prompt(template, question=question)
        user_prompt = f"Route info: {route_info}\nReturn JSON with keys: problem_parse, solution_plan, potential_tools, risk_points."
        reply = self.client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        try:
            data = json.loads(reply)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        plan = _fallback_plan(question, route_info)
        plan["risk_points"].append("planner_non_json_fallback")
        return plan


def run(question: str) -> str:
    return f"Plan for: {question}"
