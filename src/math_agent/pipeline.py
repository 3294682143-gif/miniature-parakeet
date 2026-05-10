from __future__ import annotations

import ast
import re
from datetime import datetime
from pathlib import Path

from .agents import explainer, planner, refiner, router, solver, verifier
from .clients.interns1_client import InternS1Client
from .logging_utils import now_iso, write_trace
from .schemas import FinalAnswer, MathQuestion, ProblemParse, SolveResult, ToolTrace, Verification, make_failure_result
from .tools import sympy_tools

_ALLOWED_BINARY_OPS: dict[type[ast.AST], callable] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_UNARY_OPS: dict[type[ast.AST], callable] = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}


def _eval_safe_math_expr(expr: str) -> float | int:
    tree = ast.parse(expr, mode="eval")

    def _eval_node(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY_OPS:
            return _ALLOWED_BINARY_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPS:
            return _ALLOWED_UNARY_OPS[type(node.op)](_eval_node(node.operand))
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
    for pattern in [r"最终答案\s*[：:]\s*(.+)", r"答案\s*[：:]\s*(.+)", r"Answer\s*[:：]\s*(.+)"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            line = match.group(1).strip().splitlines()[0].strip()
            return line if line else None
    return None


def _format_tool_value(value: object) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _run_tool_assist(question: str, problem_type: str, recommended_solver: str) -> tuple[str | None, Verification | None, ToolTrace]:
    q = question.strip()
    solver_hint = (recommended_solver or "").lower()
    try:
        if "等价" in q and "是否" in q:
            match = re.search(r"判断\s+(.+?)\s+是否等价于\s+(.+)$", q)
            if not match:
                return None, None, ToolTrace(tool="sympy", purpose="check equivalent", status="fail", summary="could not parse equivalence")
            left, right = match.group(1).strip(), match.group(2).strip(" ?？")
            is_eq = sympy_tools.check_equivalent(left, right)
            value = "True" if is_eq else "False"
            return value, Verification(method="symbolic_check", passed=True, notes=f"equivalent={value}"), ToolTrace(tool="sympy", purpose="check equivalent", status="success", summary=f"{left} <=> {right}: {value}")
        if "化简" in q:
            expr = q.split("化简", 1)[1].strip(" ：:？?")
            if not expr:
                return None, None, ToolTrace(tool="sympy", purpose="simplify expression", status="fail", summary="empty expression")
            simplified = sympy_tools.simplify_expression(expr)
            if simplified.startswith("ERROR:"):
                return None, None, ToolTrace(tool="sympy", purpose="simplify expression", status="fail", summary=simplified)
            return simplified, Verification(method="symbolic_check", passed=True, notes="sympy simplify passed"), ToolTrace(tool="sympy", purpose="simplify expression", status="success", summary=f"{expr} -> {simplified}")
        if "求解" in q and "=" in q:
            equation = q.split("求解", 1)[1].strip(" ：:？?")
            solved = sympy_tools.solve_equation(equation)
            if solved.startswith("ERROR:"):
                return None, None, ToolTrace(tool="sympy", purpose="solve equation", status="fail", summary=solved)
            return solved, Verification(method="substitution", passed=True, notes="sympy solve passed"), ToolTrace(tool="sympy", purpose="solve equation", status="success", summary=f"{equation} -> {solved}")
        maybe_calc = q.replace("计算", "").replace("=", "").replace("?", "").replace("？", "").strip()
        if problem_type == "calculation" or solver_hint == "program" or re.fullmatch(r"[\d\s\+\-\*/\(\)\.\^]+", maybe_calc):
            expr = maybe_calc.replace("^", "**")
            value = _format_tool_value(_eval_safe_math_expr(expr))
            return value, Verification(method="numeric_check", passed=True, notes="safe arithmetic eval passed"), ToolTrace(tool="python", purpose="arithmetic evaluation", status="success", summary=f"{expr} -> {value}")
    except Exception as exc:
        return None, None, ToolTrace(tool="python", purpose="tool assist", status="fail", summary=str(exc))
    return None, None, ToolTrace(tool="none", purpose="no suitable tool detected", status="skipped", summary="fallback to solver")


class MathAgentPipeline:
    def __init__(self, client: InternS1Client | None = None, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True, enable_tools: bool = False, max_refine_rounds: int = 1, save_trace: bool = True, trace_dir: str | Path = "outputs/traces", prompt_version: str = "default") -> None:
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
        trace_payload = {"question_id": qid, "question": question, "started_at": started_at, "finished_at": None, "latency_seconds": 0.0, "prompt_version": self.prompt_version, "route_info": {}, "model_calls": [], "tool_calls": [], "verifier_result": {}, "final_result": {}, "errors": []}
        traces: list[ToolTrace] = []
        result: SolveResult
        try:
            route_info = self.router.route(question)
            if hasattr(route_info, "model_dump"):
                trace_payload["route_info"] = route_info.model_dump()
            else:
                trace_payload["route_info"] = {
                    "domain": getattr(route_info, "domain", ""),
                    "problem_type": getattr(route_info, "problem_type", ""),
                    "recommended_solver": getattr(route_info, "recommended_solver", ""),
                    "reason": getattr(route_info, "reason", ""),
                    "confidence": getattr(route_info, "confidence", 0.0),
                }
            traces.append(ToolTrace(tool="none", purpose="route", status="success", summary=route_info.reason))
            plan = planner.run(question)
            trace_payload["model_calls"].append({"agent": "planner", "summary": str(plan)[:200]})
            draft_solution = solver.run(question)
            trace_payload["model_calls"].append({"agent": "solver", "summary": draft_solution[:300]})
            final_answer = extract_boxed_answer(draft_solution)
            status = "success"
            if not final_answer:
                final_answer = _mock_answer_from_question(question) if self.mock else None
                if not final_answer:
                    final_answer = draft_solution.strip()[:200]
                    status = "partial"
            verification_text = verifier.run(question)
            passed = True if self.mock else ("pass" in verification_text.lower())
            verification = Verification(method="self_review", passed=passed, notes=verification_text)
            trace_payload["verifier_result"] = verification.model_dump()
            traces.append(ToolTrace(tool="none", purpose="verify", status="success" if passed else "fail", summary=verification_text))
            refiner_triggered = False
            if self.enable_tools:
                tool_value, tool_verification, tool_trace = _run_tool_assist(question, route_info.problem_type, route_info.recommended_solver)
                traces.append(tool_trace)
                trace_payload["tool_calls"].append(tool_trace.model_dump())
                if tool_value is not None and tool_verification is not None:
                    final_answer, verification, status = tool_value, tool_verification, "success"
            rounds = 0
            current_solution = draft_solution
            while not verification.passed and rounds < self.max_refine_rounds:
                refiner_triggered = True
                rounds += 1
                current_solution = refiner.run(current_solution)
                traces.append(ToolTrace(tool="none", purpose="refine", status="success", summary=f"refine round {rounds}"))
                final_answer = extract_boxed_answer(current_solution) or final_answer
                verification_text = verifier.run(question)
                passed = True if self.mock else ("pass" in verification_text.lower())
                verification = Verification(method="self_review", passed=passed, notes=verification_text)
                trace_payload["verifier_result"] = verification.model_dump()
            explanation = explainer.run(question)
            trace_payload["model_calls"].append({"agent": "explainer", "summary": explanation[:200]})
            trace_payload["refiner_triggered"] = refiner_triggered
            if not verification.passed:
                status = "partial" if status == "success" else status
            confidence = route_info.confidence if route_info.confidence else 0.5
            if self.enable_tools and any(t.status == "success" and t.tool in {"python", "sympy"} for t in traces):
                confidence = max(confidence, 0.85)
            result = SolveResult(question_id=qid, domain=route_info.domain, problem_type=route_info.problem_type, problem_parse=ProblemParse(goal=question, givens=[question], symbols=[]), solution_plan=[str(plan)], visible_solution_steps=[current_solution], tool_trace=traces, final_answer=FinalAnswer(type="text", value=final_answer, boxed=f"\\boxed{{{final_answer}}}"), verification=verification, didactic_hint=explanation, confidence=max(0.0, min(1.0, confidence)), status=status, error=None)
        except Exception as exc:
            trace_payload["errors"].append(str(exc))
            result = make_failure_result(question_id=qid, question=question, error_message=str(exc))
        finally:
            finished_at = now_iso()
            trace_payload["finished_at"] = finished_at
            try:
                start_dt = datetime.fromisoformat(started_at)
                end_dt = datetime.fromisoformat(finished_at)
                trace_payload["latency_seconds"] = max(0.0, (end_dt - start_dt).total_seconds())
            except Exception:
                trace_payload["latency_seconds"] = 0.0
            trace_payload["final_result"] = result.model_dump()
            if self.save_trace:
                try:
                    write_trace(trace_payload, self.trace_dir, qid)
                except Exception:
                    pass
        return result


def solve_question(question: MathQuestion, mock: bool = True, model: str = "intern-s1", enable_tools: bool = False, save_trace: bool = True, trace_dir: str | Path = "outputs/traces") -> SolveResult:
    _ = model
    pipeline = MathAgentPipeline(mock=mock, enable_tools=enable_tools, save_trace=save_trace, trace_dir=trace_dir)
    return pipeline.solve(question.question, question.question_id)
