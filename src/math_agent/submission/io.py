from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from math_agent.io_utils import iter_bounded_utf8_lines, strict_json_loads
from math_agent.schemas import MAX_QUESTION_ID_CHARS
from math_agent.security import contains_non_finite_number


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
    raw_question_id = str(qid)
    canonical_question_id = raw_question_id.strip()
    question = row.get("question") or row.get("prompt") or ""
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    if (
        not canonical_question_id
        or len(raw_question_id) > MAX_QUESTION_ID_CHARS
        or len(canonical_question_id) > MAX_QUESTION_ID_CHARS
    ):
        canonical_question_id = f"line-{index}"
        metadata = {
            **metadata,
            "_invalid": True,
            "_error": "invalid_question_id",
        }
    return DryRunQuestion(
        # Match MathQuestion's canonical ID before duplicate detection and before
        # deriving a trace filename. Otherwise `q1` and ` q1 ` collapse only at
        # execution time and silently share one trace file.
        question_id=canonical_question_id,
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
    seen_question_ids: set[str] = set()
    for idx, line in iter_bounded_utf8_lines(path):
        if limit is not None and len(questions) >= limit:
            # Keep consuming the bounded reader so its final identity check runs.
            continue
        if not line.strip():
            continue
        try:
            parsed = strict_json_loads(line)
            if contains_non_finite_number(parsed):
                raise ValueError("non-finite values are not allowed")
        except (json.JSONDecodeError, RecursionError, ValueError):
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
        invalid_question_id = q.metadata.get("_error") == "invalid_question_id"
        if not invalid_question_id and q.question_id in seen_question_ids:
            q.metadata = {
                **q.metadata,
                "_invalid": True,
                "_error": "duplicate_question_id",
            }
        if not invalid_question_id:
            seen_question_ids.add(q.question_id)
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
