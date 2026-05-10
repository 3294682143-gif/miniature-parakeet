from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class MathQuestion(BaseModel):
    question: str
    question_id: str = Field(default="unknown")


class MathResult(BaseModel):
    question_id: str
    question: str
    answer: str
    explanation: str
    success: bool
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
