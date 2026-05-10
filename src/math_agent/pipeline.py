from __future__ import annotations

import ast
import re
from pathlib import Path
from time import perf_counter
from typing import Any

from .agents import explainer, planner, refiner, router, solver, verifier
from .clients.interns1_client import InternS1Client
from .logging_utils import now_iso, write_trace
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
        save_trace: bool = True,
        trace_dir: str | Path = "outputs/traces",
        prompt_version: str = "default",
    ) -> None:
        self.mock = mock
        self.enable_tools = enable_tools
        self.max_refine_rounds = max(0, max_refine_rounds)
        self.save_trace = save_trace
        self.trace_dir = Path(trace_dir)
        self.prompt_version = prompt_version
        self.client = client or InternS1Client(mock=mock)
        self.prompt_config_path = Path(prompt_config_path)
        self.router = router.Router(client=self.client, prompt_config_path=self.prompt_config_path)

    def solve(self, question: str, question_id: str | None = None) -> SolveResult:
        qid = question_id or "unknown"
        started_at = now_iso()
        start = perf_counter()
        trace: list[ToolTrace] = []
        trace_record: dict[str, Any] = {
            "question_id": qid,
            "question": question,
            "started_at": started_at,
            "finished_at": None,
            "latency_seconds": 0.0,
            "prompt_version": self.prompt_version,
            "route_info": {},
            "model_calls": [],
            "tool_calls": [],
            "verifier_result": {},
            "final_result": {},
            "errors": [],
        }

        try:
            route_info = self.router.route(question)
            trace_record["route_info"] = (
                route_info.model_dump()
                if hasattr(route_info, "model_dump")
                else {
                    "domain": getattr(route_info, "domain", ""),
                    "problem_type": getattr(route_info, "problem_type", ""),
                    "reason": getattr(route_info, "reason", ""),
                    "confidence": getattr(route_info, "confidence", 0.0),
                }
            )
            trace_record["model_calls"].append({"stage": "route", "summary": route_info.reason})
            trace.append(ToolTrace(tool="none", purpose="route", status="success", summary=route_info.reason))

            plan = planner.run(question)
            trace_record["model_calls"].append({"stage": "plan", "summary": str(plan)[:200]})
            trace.append(ToolTrace(tool="none", purpose="plan", status="success", summary="planning completed"))

            draft_solution = solver.run(question)
            trace_record["model_calls"].append({"stage": "solve", "summary": draft_solution[:200]})
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
            trace_record["verifier_result"] = verification.model_dump()
            trace.append(
                ToolTrace(tool="none", purpose="verify", status="success" if passed else "fail", summary=verification_text)
            )

            rounds = 0
            current_solution = draft_solution
            refined = False
            while not verification.passed and rounds < self.max_refine_rounds:
                rounds += 1
                refined = True
                current_solution = refiner.run(current_solution)
                trace_record["model_calls"].append({"stage": "refine", "summary": current_solution[:200], "round": rounds})
                trace.append(ToolTrace(tool="none", purpose="refine", status="success", summary=f"refine round {rounds}"))
                final_answer = extract_boxed_answer(current_solution) or final_answer
                verification_text = verifier.run(question)
                passed = True if self.mock else ("pass" in verification_text.lower())
                verification = Verification(method="self_review", passed=passed, notes=verification_text)
                trace_record["verifier_result"] = verification.model_dump()

            explanation = explainer.run(question)
            trace_record["model_calls"].append({"stage": "explain", "summary": explanation[:200]})
            trace.append(ToolTrace(tool="none", purpose="explain", status="success", summary="explanation completed"))

            if not verification.passed:
                status = "partial" if status == "success" else status

            result = SolveResult(
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
            trace_record["tool_calls"] = [item.model_dump() for item in trace]
            trace_record["final_result"] = result.model_dump()
            trace_record["model_calls"].append({"stage": "meta", "refiner_triggered": refined})
            return result
        except Exception as exc:
            fail = make_failure_result(question_id=qid, question=question, error_message=str(exc))
            trace_record["errors"].append(str(exc))
            trace_record["final_result"] = fail.model_dump()
            return fail
        finally:
            trace_record["finished_at"] = now_iso()
            trace_record["latency_seconds"] = round(perf_counter() - start, 6)
            if self.save_trace:
                write_trace(trace_record, self.trace_dir, qid)


def solve_question(
    question: MathQuestion,
    mock: bool = True,
    model: str = "intern-s1",
    save_trace: bool = True,
    trace_dir: str | Path = "outputs/traces",
    prompt_version: str = "default",
) -> SolveResult:
    _ = model
    pipeline = MathAgentPipeline(mock=mock, save_trace=save_trace, trace_dir=trace_dir, prompt_version=prompt_version)
    return pipeline.solve(question.question, question.question_id)
