from __future__ import annotations

import ast
import re
from pathlib import Path

from .agents import explainer, planner, refiner, router, solver, verifier
from .clients.interns1_client import InternS1Client
from .logging_utils import now_iso, write_trace
from .schemas import FinalAnswer, ProblemParse, SolveResult, ToolTrace, Verification, make_failure_result
from .tools import sympy_tools

_ALLOWED_BINARY_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: a**b}
_ALLOWED_UNARY_OPS = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}

def _eval_safe_math_expr(expr: str):
    tree = ast.parse(expr, mode="eval")
    def e(n):
        if isinstance(n, ast.Expression): return e(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _ALLOWED_BINARY_OPS: return _ALLOWED_BINARY_OPS[type(n.op)](e(n.left), e(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _ALLOWED_UNARY_OPS: return _ALLOWED_UNARY_OPS[type(n.op)](e(n.operand))
        raise ValueError("unsupported expression")
    return e(tree)

def _mock_answer_from_question(question: str) -> str | None:
    try: return str(_eval_safe_math_expr(question.replace("=", "").replace("?", "").replace("计算", "").strip()))
    except Exception: return None

def extract_boxed_answer(text: str) -> str | None:
    if not text: return None
    boxed = re.search(r"\\boxed\{([^{}]+)\}", text)
    if boxed: return boxed.group(1).strip()
    return None

def _run_tool_assist(question: str, problem_type: str, recommended_solver: str):
    q = question.strip()
    try:
        if "化简" in q:
            expr = q.split("化简", 1)[1].strip(" ：:？?")
            s = sympy_tools.simplify_expression(expr)
            if not s.startswith("ERROR:"): return s, Verification(method="symbolic_check", passed=True, notes="sympy simplify passed"), ToolTrace(tool="sympy", purpose="simplify expression", status="success", summary=s)
        if "求解" in q and "=" in q:
            eq = q.split("求解", 1)[1].strip(" ：:？?")
            s = sympy_tools.solve_equation(eq)
            if not s.startswith("ERROR:"): return s, Verification(method="substitution", passed=True, notes="sympy solve passed"), ToolTrace(tool="sympy", purpose="solve equation", status="success", summary=s)
        maybe = q.replace("计算", "").replace("=", "").replace("?", "").replace("？", "").strip()
        if problem_type == "calculation" or (recommended_solver or "").lower() == "program" or re.fullmatch(r"[\d\s\+\-\*/\(\)\.\^]+", maybe):
            v = str(_eval_safe_math_expr(maybe.replace("^", "**")))
            return v, Verification(method="numeric_check", passed=True, notes="safe arithmetic eval passed"), ToolTrace(tool="python", purpose="arithmetic", status="success", summary=v)
    except Exception as exc:
        return None, None, ToolTrace(tool="python", purpose="tool assist", status="fail", summary=str(exc))
    return None, None, ToolTrace(tool="none", purpose="tool assist", status="skipped", summary="fallback")

class MathAgentPipeline:
    def __init__(self, client: InternS1Client | None = None, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True, enable_tools: bool = False, max_refine_rounds: int = 1, save_trace: bool = True, trace_dir: str | Path = "outputs/traces", prompt_version: str = "default") -> None:
        self.mock = mock; self.enable_tools = enable_tools; self.max_refine_rounds = max(0, max_refine_rounds); self.save_trace = save_trace; self.trace_dir = Path(trace_dir); self.prompt_version = prompt_version
        self.client = client or InternS1Client(mock=mock)
        self.prompt_config_path = Path(prompt_config_path)
        self.router = router.Router(client=self.client, prompt_config_path=self.prompt_config_path)
        self.planner_agent = planner.Planner(self.client, self.prompt_config_path, mock=self.mock)
        self.solver_agent = solver.Solver(self.client, self.prompt_config_path, mock=self.mock)
        self.verifier_agent = verifier.Verifier(self.client, self.prompt_config_path, mock=self.mock)

    def solve(self, question: str, question_id: str | None = None) -> SolveResult:
        qid = question_id or "unknown"; started_at = now_iso(); trace_payload = {"question_id": qid, "question": question, "started_at": started_at, "finished_at": None, "latency_seconds": 0.0, "prompt_version": self.prompt_version, "route_info": {}, "model_calls": [], "tool_calls": [], "verifier_result": {}, "final_result": {}, "errors": []}; traces = []
        try:
            route_info = self.router.route(question)
            route_dict = route_info.model_dump() if hasattr(route_info, "model_dump") else {"domain": getattr(route_info, "domain", "unknown"), "problem_type": getattr(route_info, "problem_type", "unknown"), "recommended_solver": getattr(route_info, "recommended_solver", ""), "reason": getattr(route_info, "reason", ""), "confidence": getattr(route_info, "confidence", 0.0)}
            trace_payload["route_info"] = route_dict

            plan = self.planner_agent.plan(question, route_dict)
            draft = self.solver_agent.solve(question, route_dict, plan)
            trace_payload["model_calls"].append({"stage": "planner", "status": "ok", "model": getattr(self.client, "model", "intern-s1"), "prompt_chars": len(str(question)) + len(str(route_dict)), "response_chars": len(str(plan))})
            trace_payload["model_calls"].append({"stage": "solver", "status": "ok", "model": getattr(self.client, "model", "intern-s1"), "prompt_chars": len(str(question)) + len(str(plan)), "response_chars": len(str(draft))})

            final = extract_boxed_answer(draft)
            status = "success"
            if not final:
                final = _mock_answer_from_question(question) if self.mock else draft.strip()[:200]
                if not final: status = "partial"; final = ""

            verification = self.verifier_agent.verify(question, draft, final, route_dict)
            trace_payload["model_calls"].append({"stage": "verifier", "status": "ok", "model": getattr(self.client, "model", "intern-s1"), "prompt_chars": len(str(question)) + len(str(draft)), "response_chars": len(str(verification.notes))})

            current = draft
            if self.enable_tools:
                tv, tvf, ttrace = _run_tool_assist(question, route_dict.get("problem_type", ""), route_dict.get("recommended_solver", ""))
                traces.append(ttrace); trace_payload["tool_calls"].append(ttrace.model_dump())
                if tv is not None and tvf is not None:
                    final, verification, status = tv, tvf, "success"
                    current = f"工具校验/计算得到最终答案为 \\boxed{{{final}}}。"

            rounds = 0
            while not verification.passed and rounds < self.max_refine_rounds:
                rounds += 1
                current = refiner.run(current)
                final = extract_boxed_answer(current) or final
                verification = self.verifier_agent.verify(question, current, final, route_dict)

            if not verification.passed and status == "success": status = "partial"
            result = SolveResult(question_id=qid, domain=route_dict.get("domain", "unknown"), problem_type=route_dict.get("problem_type", "unknown"), problem_parse=ProblemParse(goal=question, givens=[question], symbols=[]), solution_plan=[str(plan)], visible_solution_steps=[current], tool_trace=traces, final_answer=FinalAnswer(type="text", value=final, boxed=f"\\boxed{{{final}}}" if final else ""), verification=verification, didactic_hint=explainer.run(question), confidence=max(0.0, min(1.0, route_dict.get("confidence", 0.5) or 0.5)), status=status, error=None)
            trace_payload["model_calls_count"] = len(trace_payload["model_calls"])
        except Exception as exc:
            trace_payload["errors"].append(str(exc)); result = make_failure_result(question_id=qid, question=question, error_message=str(exc))
        finally:
            trace_payload["finished_at"] = now_iso(); trace_payload["final_result"] = result.model_dump()
            if self.save_trace:
                try: write_trace(trace_payload, self.trace_dir, qid)
                except Exception: pass
        return result


def solve_question(question, mock: bool = True, model: str = "intern-s1", enable_tools: bool = False, save_trace: bool = True, trace_dir: str | Path = "outputs/traces"):
    _ = model
    return MathAgentPipeline(mock=mock, enable_tools=enable_tools, save_trace=save_trace, trace_dir=trace_dir).solve(question.question, question.question_id)
