from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DryRunQuestion:
    question_id: str
    question: str
    domain: str = "unknown"
    problem_type: str = "unknown"
    answer_type: str = "text"
    difficulty: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_question_record(row: dict[str, Any], index: int) -> DryRunQuestion:
    qid = row.get("question_id") or row.get("id") or row.get("qid") or f"line-{index}"
    question = row.get("question") or row.get("prompt") or ""
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return DryRunQuestion(
        question_id=str(qid),
        question=str(question),
        domain=str(row.get("domain", "unknown")),
        problem_type=str(row.get("problem_type", "unknown")),
        answer_type=str(row.get("answer_type", "text")),
        difficulty=str(row.get("difficulty", "unknown")),
        metadata=metadata,
    )


def load_dry_run_questions(
    path: Path | str, limit: int | None = None
) -> list[DryRunQuestion]:
    questions: list[DryRunQuestion] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if limit is not None and len(questions) >= limit:
                break
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                questions.append(
                    DryRunQuestion(
                        question_id=f"line-{idx}",
                        question="",
                        metadata={"_invalid": True, "_error": "invalid_json"},
                    )
                )
                continue
            if not isinstance(parsed, dict):
                questions.append(
                    DryRunQuestion(
                        question_id=f"line-{idx}",
                        question="",
                        metadata={"_invalid": True, "_error": "non_object_json"},
                    )
                )
                continue
            q = normalize_question_record(parsed, idx)
            if not q.question.strip():
                q.metadata = {
                    **q.metadata,
                    "_invalid": True,
                    "_error": "missing_question",
                }
            questions.append(q)
    return questions


def validate_dry_run_questions(questions: list[DryRunQuestion]) -> dict[str, Any]:
    invalid_count = 0
    missing_question_count = 0
    valid_count = 0
    for q in questions:
        invalid = bool(q.metadata.get("_invalid"))
        if invalid:
            invalid_count += 1
            if q.metadata.get("_error") == "missing_question":
                missing_question_count += 1
        else:
            valid_count += 1
    return {
        "total": len(questions),
        "valid": valid_count,
        "invalid": invalid_count,
        "missing_question": missing_question_count,
    }
