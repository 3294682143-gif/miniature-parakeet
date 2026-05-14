from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from math_agent.clients.interns1_client import InternS1Client
from math_agent.prompting import get_prompt, load_prompts, render_prompt


class RouteInfo(BaseModel):
    domain: str
    problem_type: str
    recommended_solver: str
    needs_tool: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class Router:
    DOMAIN_RULES: dict[str, list[str]] = {
        "PDE": ["偏微分方程", "pde", "边值问题", "boundary condition"],
        "ComplexAnalysis": ["解析函数", "留数", "围道积分", "contour integral", "residue"],
        "Topology": ["拓扑", "同胚", "紧致", "compact", "homeomorphism"],
        "Optimization": ["线性规划", "约束", "最优", "最大化", "最小化", "linear programming"],
        "Algebra": ["矩阵", "特征值", "群", "环", "域", "eigenvalue"],
        "Geometry": ["几何", "三角形", "圆", "angle", "triangle", "circle"],
        "Probability": ["概率", "期望", "方差", "随机变量", "random variable"],
        "NumberTheory": ["数列", "整除", "素数", "同余", "prime", "congruence"],
        "Calculus": ["导数", "积分", "极限", "limit", "derivative", "integral"],
    }

    PROBLEM_TYPE_RULES: dict[str, list[str]] = {
        "proof": ["证明", "show that", "prove"],
        "optimization": ["最优", "最大化", "最小化", "maximize", "minimize", "constraint"],
        "calculation": ["计算", "求", "evaluate", "compute"],
        "conceptual": ["解释", "定义", "为什么", "concept", "definition"],
    }

    PROGRAM_HINTS = ["数值", "方程", "积分", "矩阵", "表达式", "equation", "integral", "matrix", "expression"]
    TOOL_HINTS = ["计算", "求解", "solve", "compute", "evaluate"]

    def __init__(
        self,
        mode: str = "rule_based",
        client: InternS1Client | None = None,
        prompt_config_path: str | Path = "configs/prompts.yaml",
    ) -> None:
        if mode not in {"rule_based", "llm"}:
            raise ValueError("mode must be one of: rule_based, llm")
        self.mode = mode
        self.client = client or InternS1Client(mock=True)
        self.prompt_config_path = Path(prompt_config_path)

    def route(self, question: str) -> RouteInfo:
        if self.mode == "llm":
            llm_result = self._route_with_llm(question)
            if llm_result is not None:
                return llm_result
        return self._route_rule_based(question)

    def _route_rule_based(self, question: str) -> RouteInfo:
        text = question.lower()

        domain, domain_hits = self._detect_domain(text)
        problem_type, type_hits = self._detect_problem_type(text)
        recommended_solver = self._recommend_solver(text, domain, problem_type)
        needs_tool = self._needs_tool(text, domain, recommended_solver)

        hit_count = len(domain_hits) + len(type_hits)
        confidence = min(0.99, 0.35 + 0.15 * hit_count)
        if domain == "Unknown" and problem_type == "unknown":
            confidence = 0.2

        reason = (
            f"domain={domain} via {domain_hits or ['no-keyword']}; "
            f"problem_type={problem_type} via {type_hits or ['no-keyword']}; "
            f"solver={recommended_solver}; needs_tool={needs_tool}"
        )

        return RouteInfo(
            domain=domain,
            problem_type=problem_type,
            recommended_solver=recommended_solver,
            needs_tool=needs_tool,
            confidence=confidence,
            reason=reason,
        )

    def _route_with_llm(self, question: str) -> RouteInfo | None:
        try:
            prompts = load_prompts(self.prompt_config_path)
            system_template = get_prompt(prompts, "router_system")
            system_prompt = render_prompt(system_template)
            user_prompt = (
                "Classify and route this math question. Return strict JSON only with fields: "
                "domain, problem_type, recommended_solver, needs_tool, confidence, reason.\n"
                f"Question:\n{question}"
            )
            content = self.client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            data = self._extract_json(content)
            return RouteInfo.model_validate(data)
        except (
            ValidationError,
            ValueError,
            TypeError,
            KeyError,
            FileNotFoundError,
            json.JSONDecodeError,
        ):
            return None

    @staticmethod
    def _extract_json(content: str) -> dict:
        content = content.strip()
        if content.startswith("{") and content.endswith("}"):
            return json.loads(content)
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            return json.loads(match.group(0))
        raise ValueError("No JSON object found")

    def _detect_domain(self, text: str) -> tuple[str, list[str]]:
        for domain, keywords in self.DOMAIN_RULES.items():
            hits = [k for k in keywords if k in text]
            if hits:
                return domain, hits
        return "Unknown", []

    def _detect_problem_type(self, text: str) -> tuple[str, list[str]]:
        equation_hits: list[str] = []
        if "=" in text and any(k in text for k in ["解方程", "求解", "solve", "解 "]):
            equation_hits.append("equation-intent")
        if "=" in text and re.search(r"[a-z]\s*=", text):
            equation_hits.append("single-var-equation")
        if equation_hits:
            return "calculation", equation_hits
        for problem_type in ["proof", "optimization", "calculation", "conceptual"]:
            keywords = self.PROBLEM_TYPE_RULES[problem_type]
            hits = [k for k in keywords if k in text]
            if hits:
                return problem_type, hits
        return "unknown", []

    def _recommend_solver(self, text: str, domain: str, problem_type: str) -> str:
        if problem_type == "proof":
            return "proof"
        if problem_type == "optimization" or domain == "Optimization":
            return "optimization"
        if problem_type in {"calculation", "derivation"} and any(h in text for h in self.PROGRAM_HINTS):
            return "program"
        return "general"

    def _needs_tool(self, text: str, domain: str, recommended_solver: str) -> bool:
        if domain == "Unknown":
            return False
        if recommended_solver in {"program", "optimization"}:
            return True
        if recommended_solver == "proof":
            return False
        return any(h in text for h in self.TOOL_HINTS)
