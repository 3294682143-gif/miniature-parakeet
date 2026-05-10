from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt
from math_agent.schemas import Verification
from math_agent.tools.answer_normalizer import normalize_answer
from math_agent.tools.sympy_tools import check_equivalent, numeric_compare


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

    def _tool_verify(self, draft_solution: str, final_answer: str) -> Verification | None:
        normalized_draft = normalize_answer(draft_solution)
        normalized_final = normalize_answer(final_answer)

        if numeric_compare(normalized_draft, normalized_final):
            return Verification(method="numeric_check", passed=True, notes="Numeric consistency passed.")

        if check_equivalent(normalized_draft, normalized_final):
            return Verification(method="symbolic_check", passed=True, notes="Symbolic equivalence passed.")

        if normalized_draft and normalized_final and normalized_final in normalized_draft:
            return Verification(method="substitution", passed=True, notes="Final answer appears in derivation.")

        return None

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
            tool_result = self._tool_verify(draft_solution=draft_solution, final_answer=final_answer)
            if tool_result is not None:
                return tool_result
        except Exception:
            pass

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
        return Verification(method="self_review", passed=False, notes="Verifier fallback: unable to confirm correctness.")


def run(question: str) -> str:
    _ = question
    return "pass"
