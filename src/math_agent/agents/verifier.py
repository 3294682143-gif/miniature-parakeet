from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.prompting import get_prompt, load_prompts, render_prompt
from math_agent.schemas import Verification
from math_agent.tools.answer_normalizer import normalize_answer
from math_agent.tools.sympy_tools import check_equivalent, numeric_compare


class Verifier:
    def __init__(self, client: Any, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = load_prompts(self.prompt_config_path)

    def _tool_verify(self, draft_solution: str, final_answer: str) -> Verification | None:
        nd, nf = normalize_answer(draft_solution), normalize_answer(final_answer)
        if numeric_compare(nd, nf):
            return Verification(method="numeric_check", passed=True, notes="Numeric consistency passed.")
        if check_equivalent(nd, nf):
            return Verification(method="symbolic_check", passed=True, notes="Symbolic equivalence passed.")
        if nd and nf and nf in nd:
            return Verification(method="substitution", passed=True, notes="Final answer appears in derivation.")
        return None

    def verify(self, question: str, draft_solution: str, final_answer: str, route_info: dict | None = None) -> Verification:
        if self.mock:
            return Verification(method="self_review", passed=True, notes="Mock verification passed.")
        try:
            tv = self._tool_verify(draft_solution, final_answer)
            if tv is not None:
                return tv
        except Exception:
            pass
        try:
            template = get_prompt(self.prompts, "verifier_system")
            system_prompt = render_prompt(template, question=question, draft_solution=draft_solution)
            reply = self.client.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Final answer: {final_answer}\nRoute info: {route_info}\nReturn JSON with method/passed/notes."},
            ])
            data = json.loads(reply)
            if isinstance(data, dict):
                return Verification.model_validate(data)
        except Exception:
            pass
        return Verification(method="self_review", passed=False, notes="Verifier fallback: non-JSON or invalid JSON response.")

def run(question: str) -> str:
    _ = question
    return "pass"
