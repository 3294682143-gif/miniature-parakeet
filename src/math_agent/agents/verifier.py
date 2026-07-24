from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from math_agent.agents.proof_guardian import check_proof_structure, detect_proof_problem
from math_agent.io_utils import strict_json_loads
from math_agent.prompting import freeze_prompts, get_prompt, load_prompts, render_prompt
from math_agent.schemas import Verification
from math_agent.tools.answer_normalizer import (
    extract_answer_by_patterns,
    extract_boxed_answers,
    normalize_answer,
)
from math_agent.tools.sympy_tools import check_equivalent, numeric_compare


class Verifier:
    def __init__(
        self,
        client: Any,
        prompt_config_path: str | Path = "configs/prompts.yaml",
        mock: bool = True,
        prompts: Mapping[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.prompt_config_path = Path(prompt_config_path)
        self.mock = mock
        self.prompts = freeze_prompts(
            prompts if prompts is not None else load_prompts(self.prompt_config_path)
        )

    def _tool_verify(
        self, draft_solution: str, final_answer: str
    ) -> Verification | None:
        nd, nf = normalize_answer(draft_solution), normalize_answer(final_answer)
        if numeric_compare(nd, nf):
            return Verification(
                method="numeric_check", passed=True, notes="Numeric consistency passed."
            )
        if check_equivalent(nd, nf):
            return Verification(
                method="symbolic_check",
                passed=True,
                notes="Symbolic equivalence passed.",
            )
        draft_boxes = [
            normalize_answer(value) for value in extract_boxed_answers(draft_solution)
        ]
        explicit_answer = extract_answer_by_patterns(draft_solution)
        normalized_explicit = (
            normalize_answer(explicit_answer) if explicit_answer is not None else ""
        )
        if nf and (nf in draft_boxes or normalized_explicit == nf):
            return Verification(
                method="substitution",
                passed=True,
                notes="Final answer has explicit derivation evidence.",
            )
        final_parts = _list_parts(nf)
        if final_parts:
            if all(part in draft_boxes for part in final_parts):
                return Verification(
                    method="substitution",
                    passed=True,
                    notes="All final answer components are explicitly boxed.",
                )
        return None

    def verify(
        self,
        question: str,
        draft_solution: str,
        final_answer: str,
        route_info: dict | None = None,
    ) -> Verification:
        is_proof = detect_proof_problem(question, route_info)
        if self.mock:
            return Verification(
                method="self_review", passed=True, notes="Mock verification passed."
            )

        proof_structure: Verification | None = None
        consistency_diagnostic: Verification | None = None
        if is_proof:
            try:
                proof_structure = check_proof_structure(question, draft_solution)
                if not proof_structure.passed:
                    return proof_structure
            except Exception:
                proof_structure = None
        else:
            try:
                consistency_diagnostic = self._tool_verify(draft_solution, final_answer)
            except Exception:
                pass
        try:
            template = get_prompt(self.prompts, "verifier_system")
            system_prompt = render_prompt(
                template, question=question, draft_solution=draft_solution
            )
            reply = self.client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Final answer: {final_answer}\n"
                            f"Route info: {route_info}\n"
                            "Draft/final consistency is not evidence that the answer "
                            "solves the question. Independently verify correctness.\n"
                            "Return JSON with method/passed/notes."
                        ),
                    },
                ]
            )
            data = strict_json_loads(reply)
            if isinstance(data, dict) and type(data.get("passed")) is bool:
                independent = Verification.model_validate(data)
                if independent.passed and consistency_diagnostic is not None:
                    return Verification(
                        method=consistency_diagnostic.method,
                        passed=True,
                        notes=(
                            f"Independent verifier passed: {independent.notes} | "
                            f"Consistency diagnostic: {consistency_diagnostic.notes}"
                        ),
                    )
                return independent
        except Exception:
            pass
        return Verification(
            method="self_review",
            passed=False,
            notes=(
                "Verifier fallback: non-JSON or invalid JSON response."
                + (
                    f" Structural diagnostics: {proof_structure.notes}"
                    if proof_structure is not None
                    else ""
                )
                + (
                    f" Consistency diagnostics: {consistency_diagnostic.notes}"
                    if consistency_diagnostic is not None
                    else ""
                )
            ),
        )


def run(question: str) -> str:
    _ = question
    return "pass"


def _list_parts(value: str) -> list[str]:
    text = (value or "").strip()
    if not text.startswith("[") or not text.endswith("]"):
        return []
    return [
        normalize_answer(part)
        for part in text.strip("[]").split(",")
        if normalize_answer(part)
    ]
