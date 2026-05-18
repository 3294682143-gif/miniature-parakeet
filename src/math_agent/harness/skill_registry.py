from __future__ import annotations

from pathlib import Path
from typing import Any

from math_agent.agents.proof_guardian import detect_proof_problem


class SkillRegistry:
    def __init__(self, root: str = "skills") -> None:
        self.root = Path(root)

    def list_skills(self) -> list[str]:
        if not self.root.exists() or not self.root.is_dir():
            return []
        skills: list[str] = []
        for path in sorted(self.root.glob("*.skill.md")):
            name = path.name.removesuffix(".skill.md")
            if name:
                skills.append(name)
        return skills

    def load_skill(self, name: str) -> dict[str, Any]:
        normalized = self._normalize_name(name)
        path = self.root / f"{normalized}.skill.md"
        text = path.read_text(encoding="utf-8")
        metadata = self.parse_skill_metadata(text)
        metadata.setdefault("name", normalized)
        metadata["raw_text"] = text
        metadata["path"] = str(path)
        return metadata

    def safe_load_skill(self, name: str) -> dict[str, Any] | None:
        try:
            return self.load_skill(name)
        except (OSError, ValueError):
            return None

    def parse_skill_metadata(self, text: str) -> dict[str, str]:
        fields = {
            "name",
            "applies_to",
            "input_features",
            "procedure",
            "heuristics",
            "constraints",
            "fallback",
            "final_answer_rules",
            "trace_notes",
        }
        meta: dict[str, str] = {}
        current_key: str | None = None
        buffer: list[str] = []

        def flush() -> None:
            nonlocal current_key, buffer
            if current_key is not None:
                meta[current_key] = "\n".join(buffer).strip()
            current_key = None
            buffer = []

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip() and current_key is not None:
                buffer.append("")
                continue

            if ":" in line:
                candidate, rest = line.split(":", 1)
                key = candidate.strip()
                if key in fields and line.lstrip() == line:
                    flush()
                    current_key = key
                    value = rest.strip()
                    if value:
                        buffer.append(value)
                    continue
            if current_key is not None:
                buffer.append(line)
        flush()
        return meta

    def select_skill(self, route_info: dict[str, Any] | None = None, question: str | None = None) -> str | None:
        question_text = question or ""
        if detect_proof_problem(question_text, route_info=route_info):
            return "proof" if self.safe_load_skill("proof") else self._fallback_general()

        rt = route_info or {}
        domain = str(rt.get("domain", "") or "").lower()
        ptype = str(rt.get("problem_type", "") or "").lower()
        combined = " ".join([question_text.lower(), domain, ptype])

        keyword_map: list[tuple[str, tuple[str, ...]]] = [
            ("equation", ("equation", "方程", "solve", "解方程", "=", "unknown")),
            ("calculation", ("calculation", "计算", "compute", "evaluate", "求值")),
            ("probability", ("probability", "随机", "概率", "expectation", "variance")),
            ("geometry", ("geometry", "triangle", "circle", "几何", "角")),
            ("matrix", ("matrix", "矩阵", "eigen", "determinant", "线性代数")),
            ("optimization", ("optimization", "maximize", "minimize", "最优", "约束")),
            ("calculus", ("integral", "derivative", "limit", "微分", "积分", "极限")),
        ]

        for skill, hints in keyword_map:
            if any(h in combined for h in hints):
                return skill if self.safe_load_skill(skill) else self._fallback_general()

        return self._fallback_general()

    def _fallback_general(self) -> str | None:
        if self.safe_load_skill("general"):
            return "general"
        return None

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = (name or "").strip().lower()
        if not normalized:
            raise ValueError("skill name cannot be empty")
        return normalized
