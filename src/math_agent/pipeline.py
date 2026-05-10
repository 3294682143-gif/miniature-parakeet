from __future__ import annotations

import ast
import re
from pathlib import Path

from .agents import explainer, planner, refiner, router, solver, verifier
from .clients.interns1_client import InternS1Client
from .schemas import FinalAnswer, MathQuestion, ProblemParse, SolveResult, ToolTrace, Verification, make_failure_result




_ALLOWED_BINARY_OPS: dict[type[ast.AST], callable] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_UNARY_OPS: dict[type[ast.AST], callable] = {
    ast.UAdd: lambda a: a,
    ast.USub: lambda a: -a,
}


def _eval_safe_math_expr(expr: str) -> float | int:
    tree = ast.parse(expr, mode="eval")

    def _eval_node(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY_OPS:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            return _ALLOWED_BINARY_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPS:
            operand = _eval_node(node.operand)
            return _ALLOWED_UNARY_OPS[type(node.op)](operand)
        raise ValueError("unsupported expression")

    return _eval_node(tree)


def _mock_answer_from_question(question: str) -> str | None:
    normalized = question.replace("=", "").replace("?", "").replace("计算", "").strip()
    try:
        return str(_eval_safe_math_expr(normalized))
    except Exception:
        return None

def extract_boxed_answer(text: str) -> str | None:
    if not text:
        return None

    boxed = re.search(r"\\boxed\{([^{}]+)\}", text)
    if boxed:
        return boxed.group(1).strip()

    patterns = [
        r"最终答案\s*[：:]\s*(.+)",
        r"答案\s*[：:]\s*(.+)",
        r"Answer\s*[:：]\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            line = match.group(1).strip().splitlines()[0].strip()
            return line if line else None
    return None


class MathAgentPipeline:
    def __init__(
        self,
        client: InternS1Client | None = None,
        prompt_config_path: str | Path = "configs/prompts.yaml",
        mock: bool = True,
        enable_tools: bool = False,
        max_refine_rounds: int = 1,
    ) -> None:
        self.mock = mock
        self.enable_tools = enable_tools
        self.max_refine_rounds = max(0, max_refine_rounds)
        self.client = client or InternS1Client(mock=mock)
        self.prompt_config_path = Path(prompt_config_path)
        self.router = router.Router(client=self.client, prompt_config_path=self.prompt_config_path)

    def solve(self, question: str, question_id: str | None = None) -> SolveResult:
        qid = question_id or "unknown"
        trace: list[ToolTrace] = []
        try:
            route_info = self.router.route(question)
            trace.append(ToolTrace(tool="none", purpose="route", status="success", summary=route_info.reason))

            plan = planner.run(question)
            trace.append(ToolTrace(tool="none", purpose="plan", status="success", summary="planning completed"))

            draft_solution = solver.run(question)
            trace.append(ToolTrace(tool="none", purpose="solve", status="success", summary="solver completed"))

            final_answer = extract_boxed_answer(draft_solution)
            status = "success"
            if not final_answer:
                if self.mock:
                    final_answer = _mock_answer_from_question(question)
                if not final_answer:
                    final_answer = draft_solution.strip()[:200]
                    status = "partial"

            verification_text = verifier.run(question)
            passed = True if self.mock else ("pass" in verification_text.lower())
            verification = Verification(method="self_review", passed=passed, notes=verification_text)
            trace.append(
                ToolTrace(tool="none", purpose="verify", status="success" if passed else "fail", summary=verification_text)
            )

            rounds = 0
            current_solution = draft_solution
            while not verification.passed and rounds < self.max_refine_rounds:
                rounds += 1
                current_solution = refiner.run(current_solution)
                trace.append(ToolTrace(tool="none", purpose="refine", status="success", summary=f"refine round {rounds}"))
                final_answer = extract_boxed_answer(current_solution) or final_answer
                verification_text = verifier.run(question)
                passed = True if self.mock else ("pass" in verification_text.lower())
                verification = Verification(method="self_review", passed=passed, notes=verification_text)

            explanation = explainer.run(question)
            trace.append(ToolTrace(tool="none", purpose="explain", status="success", summary="explanation completed"))

            if not verification.passed:
                status = "partial" if status == "success" else status

            return SolveResult(
                question_id=qid,
                domain=route_info.domain,
                problem_type=route_info.problem_type,
                problem_parse=ProblemParse(goal=question, givens=[question], symbols=[]),
                solution_plan=[str(plan)],
                visible_solution_steps=[current_solution],
                tool_trace=trace,
                final_answer=FinalAnswer(type="text", value=final_answer, boxed=final_answer),
                verification=verification,
                didactic_hint=explanation,
                confidence=max(0.0, min(1.0, route_info.confidence if route_info.confidence else 0.5)),
                status=status,
                error=None,
            )
        except Exception as exc:
            return make_failure_result(question_id=qid, question=question, error_message=str(exc))


def solve_question(question: MathQuestion, mock: bool = True, model: str = "intern-s1") -> SolveResult:
    _ = model
    pipeline = MathAgentPipeline(mock=mock)
    return pipeline.solve(question.question, question.question_id)
