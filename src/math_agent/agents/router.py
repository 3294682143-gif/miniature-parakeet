from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from math_agent.clients.interns1_client import InternS1Client
from math_agent.prompting import get_prompt, load_prompts, render_prompt
from math_agent.typing import ChatClient


class RouteInfo(BaseModel):
    domain: str
    problem_type: str
    recommended_solver: str
    needs_tool: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class Router:
    DOMAIN_RULES: dict[str, list[str]] = {
        "PDE": [
            "偏微分",
            "边值",
            "pde",
            "boundary condition",
            "鍋忓井鍒嗘柟绋",
            "杈瑰€",
        ],
        "ComplexAnalysis": [
            "contour integral",
            "residue theorem",
            "complex analysis",
            "留数",
        ],
        "Topology": ["topology", "compact", "homeomorphism", "同胚", "鎷撴墤"],
        "OperationsResearch": [
            "linear program",
            "linear programming",
            "bounded polytope",
            "extreme point",
            "shortest path",
            "dijkstra",
            "eoq",
            "queue",
            "max-flow",
            "min-cut",
        ],
        "Optimization": [
            "linear programming",
            "线性规划",
            "约束",
            "最大化",
            "最小化",
            "最优",
            "maximize",
            "minimize",
            "constraint",
            "鏈€澶у寲",
            "鏈€灏忓寲",
            "绾挎€",
        ],
        "Algebra": [
            "eigenvalue",
            "矩阵",
            "特征值",
            "特征向量",
            "matrix",
            "equation",
            "polynomial",
            "quadratic",
            "linear",
            "鐭╅樀",
        ],
        "Geometry": [
            "geometry",
            "angle",
            "triangle",
            "circle",
            "rectangle",
            "midpoint",
            "distance",
            "coordinate",
            "area",
            "inradius",
            "chord",
            "side lengths",
            "right triangle",
            "median",
            "鍑犱綍",
        ],
        "Probability": [
            "probability",
            "概率",
            "随机变量",
            "期望",
            "方差",
            "coin",
            "dice",
            "binomial",
            "random variable",
            "expected value",
            "variance",
            "闅忔満鍙橀噺",
            "姒傜巼",
        ],
        "Combinatorics": ["choose", "combination", "permutation", "arrangement"],
        "NumberTheory": [
            "number theory",
            "素数",
            "同余",
            "整除",
            "prime",
            "congruence",
            "gcd",
            "lcm",
            "remainder",
            "divisible",
            "modulo",
            "modular",
            "least nonnegative residue",
            "euler phi",
            "positive divisors",
            "multiplicative inverse",
            "congruence system",
            "绱犳暟",
            "鍚屼綑",
        ],
        "Calculus": [
            "derivative",
            "integral",
            "limit",
            "导数",
            "求导",
            "积分",
            "极限",
            "瀵兼暟",
            "绉垎",
            "鏋侀檺",
        ],
        "Recurrence": [
            "recurrence",
            "sequence",
            "arithmetic sequence",
            "geometric sequence",
        ],
        "Functions": ["function", "f(x)", "g(x)", "functional equation", "composition"],
    }

    SPECIFIC_PROBLEM_TYPE_RULES: dict[str, list[str]] = {
        "derivative": ["derivative", "differentiate"],
        "limit": ["limit as", "approaches"],
        "definite_integral": ["definite integral", "integral from"],
        "combination": ["choose", "combination"],
        "binomial_probability": ["exactly", "heads", "coin"],
        "gcd": ["gcd"],
        "lcm": ["lcm"],
        "modular_exponent": ["least nonnegative residue"],
        "totient": ["euler phi", "phi("],
        "divisor_count": ["positive divisors"],
        "modular_inverse": ["multiplicative inverse", "least positive inverse"],
        "crt": ["least nonnegative solution"],
        "modular_arithmetic": ["remainder", "modulo", "mod "],
        "coordinate_geometry": ["squared distance", "midpoint", "coordinate"],
        "inradius": ["inradius"],
        "chord_length": ["chord"],
        "area": ["area", "rectangle", "triangle", "circle", "side lengths"],
        "arithmetic_sequence": ["arithmetic sequence"],
        "geometric_sequence": ["geometric sequence"],
        "recurrence": ["recurrence"],
        "function_evaluation": ["compute f("],
        "function_composition": ["f(g("],
        "functional_equation": ["functional equation"],
    }

    PROBLEM_TYPE_RULES: dict[str, list[str]] = {
        "proof": ["证明", "prove", "show that", "璇佹槑"],
        "optimization": [
            "maximize",
            "minimize",
            "constraint",
            "最大化",
            "最小化",
            "约束",
            "最优",
            "鏈€澶у寲",
            "鏈€灏忓寲",
            "鏈€浼",
        ],
        "calculation": [
            "calculate",
            "evaluate",
            "compute",
            "solve",
            "计算",
            "求",
            "解方程",
            "璁＄畻",
            "姹",
        ],
        "conceptual": ["concept", "definition", "explain", "定义", "解释", "瑙ｉ噴"],
    }

    PROGRAM_HINTS = [
        "number",
        "equation",
        "integral",
        "matrix",
        "expression",
        "polynomial",
        "sequence",
        "function",
        "probability",
        "area",
        "distance",
        "数值",
        "方程",
        "积分",
        "矩阵",
        "表达式",
        "璁＄畻",
        "鏂圭▼",
        "绉垎",
        "琛ㄨ揪寮",
    ]
    TOOL_HINTS = [
        "calculate",
        "solve",
        "compute",
        "evaluate",
        "计算",
        "求解",
        "璁＄畻",
        "姹傝В",
    ]
    PROGRAM_TYPES = {
        "calculation",
        "derivation",
        "linear_equation",
        "quadratic_equation",
        "derivative",
        "limit",
        "definite_integral",
        "combination",
        "binomial_probability",
        "gcd",
        "lcm",
        "modular_arithmetic",
        "modular_exponent",
        "totient",
        "divisor_count",
        "modular_inverse",
        "crt",
        "coordinate_geometry",
        "area",
        "inradius",
        "chord_length",
        "arithmetic_sequence",
        "geometric_sequence",
        "recurrence",
        "function_evaluation",
        "function_composition",
    }

    def __init__(
        self,
        mode: str = "rule_based",
        client: ChatClient | None = None,
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
        if re.search(r"\bsolve\b.*=", text):
            return "Algebra", ["solve-equation"]
        return "Unknown", []

    def _detect_problem_type(self, text: str) -> tuple[str, list[str]]:
        proof_hits = [k for k in self.PROBLEM_TYPE_RULES["proof"] if k in text]
        if proof_hits:
            return "proof", proof_hits

        for problem_type, keywords in self.SPECIFIC_PROBLEM_TYPE_RULES.items():
            hits = [k for k in keywords if k in text]
            if hits:
                return problem_type, hits

        equation_hits: list[str] = []
        if "=" in text and any(
            k in text
            for k in ["solve", "解方程", "求解", "解", "瑙ｆ柟绋", "姹傝В", "瑙"]
        ):
            equation_hits.append("equation-intent")
        if "=" in text and re.search(r"[a-z]\s*=", text):
            equation_hits.append("single-var-equation")
        if equation_hits:
            if "solve:" in text or "solve the" in text:
                if "x**2" in text or "x^2" in text:
                    return "quadratic_equation", equation_hits
                return "linear_equation", equation_hits
            return "calculation", equation_hits

        for problem_type in ["optimization", "calculation", "conceptual"]:
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
        if problem_type in self.PROGRAM_TYPES and (
            problem_type != "calculation" or any(h in text for h in self.PROGRAM_HINTS)
        ):
            return "program"
        return "general"

    def _needs_tool(self, text: str, domain: str, recommended_solver: str) -> bool:
        if recommended_solver in {"program", "optimization"}:
            return True
        if domain == "Unknown":
            return False
        if recommended_solver == "proof":
            return False
        return any(h in text for h in self.TOOL_HINTS)
