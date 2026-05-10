from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt
from math_agent.schemas import Verification


def safe_json_loads(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class Verifier:
    def __init__(self, client: Any, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)

    def verify(
        self,
        question: str,
        draft_solution: str,
        final_answer: str,
        route_info: dict | None = None,
    ) -> Verification:
        if self.mock:
            return Verification(method="self_review", passed=True, notes="Mock verification passed.")

        try:
            template = get_prompt(self.prompts, "verifier_system")
            system_prompt = render_prompt(template, question=question, draft_solution=draft_solution)
            reply = self.client.chat([
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Final answer: {final_answer}\nRoute info: {route_info}\nReturn JSON with method/passed/notes.",
                },
            ])
            parsed = safe_json_loads(reply)
            if parsed is not None:
                return Verification.model_validate(parsed)
        except Exception:
            pass
        return Verification(method="self_review", passed=False, notes="Verifier fallback: invalid model output.")
