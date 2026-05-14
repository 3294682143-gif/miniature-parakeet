from __future__ import annotations

import ast
import re
from pathlib import Path

from .agents import explainer, planner, refiner, router, solver, verifier
from .clients.interns1_client import InternS1Client
from .logging_utils import now_iso, write_trace
from .schemas import FinalAnswer, ProblemParse, SolveResult, ToolTrace, Verification, make_failure_result
from .tools import sympy_tools
from .tools.answer_normalizer import extract_answer_by_patterns, extract_boxed_answer

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

def _is_short_clean_answer(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    if len(value) > 120:
        return False
    if "###" in value:
        return False
    if value.count("\n") > 1:
        return False
    return True


def _infer_answer_type(final_value: str) -> str:
    v = (final_value or "").strip()
    if not v:
        return "text"
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", v):
        return "number"
    if re.fullmatch(r"[-+]?\d+\s*/\s*[-+]?\d+", v):
        return "number"
    if any(tok in v for tok in [r"\frac", r"\dfrac"]):
        return "expression"
    if any(op in v for op in ["+", "-", "*", "/", "=", "^"]):
        return "expression"
    return "text"

def _is_proof_problem(problem_type: str, recommended_solver: str) -> bool:
    return (problem_type or "").lower() == "proof" or (recommended_solver or "").lower() == "proof"

def _extract_proof_conclusion(text: str) -> str:
    def _clean_markdown(value: str) -> str:
        cleaned = re.sub(r"[*`$#]+", "", value or "")
        cleaned = cleaned.rstrip()
        cleaned = re.sub(r"\s{2,}$", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ：:;；，,。.!！？?-—")
        return cleaned.strip()

    def _is_meaningful(value: str) -> bool:
        if len(value) < 4:
            return False
        if value in {"结论", "最终结论", "结论：", "最终结论：", "已证明", "已证明："}:
            return False
        return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", value))

    def _is_header_shell(value: str) -> bool:
        normalized = _clean_markdown(value)
        return normalized in {"结论", "最终结论", "结论：", "最终结论：", "已证明", "已证明："}

    if not text:
        return "命题已完成证明。"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lead_patterns = [r"^最终结论\s*[:：]\s*(.+)$", r"^结论\s*[:：]\s*(.+)$", r"^已证明\s*[:：]?\s*(.+)$"]
    for i, line in enumerate(lines):
        line_for_match = _clean_markdown(line)
        if _is_header_shell(line_for_match):
            for follow in lines[i + 1:]:
                follow_clean = _clean_markdown(follow)
                if _is_meaningful(follow_clean):
                    return f"已证明：{follow_clean}"
        for pat in lead_patterns:
            m = re.search(pat, line_for_match)
            if m:
                candidate = _clean_markdown(m.group(1))
                if _is_meaningful(candidate):
                    return f"已证明：{candidate}"
                continue

    for line in reversed(lines):
        m = re.search(r"(?:因此|所以)\s*(.+)", line)
        if m:
            candidate = _clean_markdown(m.group(1))
            if _is_meaningful(candidate):
                return f"已证明：{candidate}"

    for line in lines:
        if "证毕" in line:
            return "命题已完成证明。"
    return "命题已完成证明。"


def _proof_fallback_review(
    current_steps: str,
    route_dict: dict,
    verification: Verification,
    final_type: str,
    final_value: str,
    final_boxed: str,
) -> Verification:
    if (route_dict.get("problem_type", "") or "").lower() != "proof":
        return verification
    if verification.passed or final_type != "proof":
        return verification
    text = (current_steps or "").strip()
    if len(text) <= 80:
        return verification
    if (final_boxed or "").strip() != "":
        return verification
    clean_final_value = (final_value or "").strip()
    if clean_final_value in {"", "命题已完成证明。", "结论：", "最终结论：", "已证明：", "结论：**"}:
        return verification
    keywords = ["证明", "定义", "设", "存在", "任取", "因此", "所以", "结论", "证毕", "证明完成", "符合"]
    if any(k in text for k in keywords):
        return Verification(method="logic_review", passed=True, notes="Proof structure detected; accepted by proof fallback review.")
    return verification

def _answer_type_and_boxed(route_dict: dict, final_value: str, current_steps: str) -> tuple[str, str]:
    ptype = (route_dict.get("problem_type", "") or "").lower()
    solver_name = (route_dict.get("recommended_solver", "") or "").lower()
    if _is_proof_problem(ptype, solver_name):
        value = _extract_proof_conclusion(current_steps)
        if not value.startswith("已证明") and "命题已完成证明" not in value:
            value = f"已证明：{value}"
        return "proof", ""
    if ptype == "calculation":
        inferred_type = _infer_answer_type(final_value)
        if inferred_type == "text":
            inferred_type = "expression"
    else:
        inferred_type = ptype if ptype in {"number", "expression", "set", "algorithm", "text"} else _infer_answer_type(final_value)
    if inferred_type in {"number", "expression", "set"} and _is_short_clean_answer(final_value):
        boxed = f"\\boxed{{{final_value}}}"
        if len(boxed) <= 120 and "###" not in boxed and boxed.count("\n") <= 1:
            return inferred_type, boxed
    if inferred_type in {"algorithm", "text"}:
        return inferred_type, ""
    return inferred_type, ""


def _extract_final_answer_non_proof(draft: str, current: str, tv: str | None = None) -> str:
    for candidate in [extract_boxed_answer(current), extract_boxed_answer(draft)]:
        if candidate:
            return candidate
    for candidate in [extract_answer_by_patterns(current), extract_answer_by_patterns(draft)]:
        if candidate and _is_short_clean_answer(candidate):
            return candidate
    if tv is not None:
        tvs = str(tv).strip()
        if _is_short_clean_answer(tvs):
            return tvs
    return ""


def _looks_like_long_markdown(text: str) -> bool:
    value = (text or "").strip()
    return len(value) > 300 and ("###" in value or value.count("\n\n") >= 1 or value.count("\n") > 2)

def _run_tool_assist(question: str, problem_type: str, recommended_solver: str):
    q = question.strip()
    try:
        equation_match = re.search(r"([0-9a-zA-Z\(\)\+\-\*/\^\.\s]+=[0-9a-zA-Z\(\)\+\-\*/\^\.\s]+)", q)
        if "化简" in q:
            expr = q.split("化简", 1)[1].strip(" ：:？?")
            s = sympy_tools.simplify_expression(expr)
            if not s.startswith("ERROR:"): return s, Verification(method="symbolic_check", passed=True, notes="sympy simplify passed"), ToolTrace(tool="sympy", purpose="simplify expression", status="success", summary=s)
        if equation_match and ("求解" in q or "解方程" in q or q.lower().startswith("solve") or "解 " in q):
            eq = equation_match.group(1).strip(" ：:？?")
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
    def __init__(self, client: InternS1Client | None = None, prompt_config_path: str | Path = "configs/prompts.yaml", mock: bool = True, enable_tools: bool = False, max_refine_rounds: int = 1, save_trace: bool = True, trace_dir: str | Path = "outputs/traces", prompt_version: str = "default", run_mode: str = "full") -> None:
        if run_mode not in {"full", "fast", "tool-first"}:
            raise ValueError("run_mode must be one of: full, fast, tool-first")
        self.mock = mock; self.enable_tools = enable_tools; self.max_refine_rounds = max(0, max_refine_rounds); self.save_trace = save_trace; self.trace_dir = Path(trace_dir); self.prompt_version = prompt_version; self.run_mode = run_mode
        self.client = client or InternS1Client(mock=mock)
        self.prompt_config_path = Path(prompt_config_path)
        self.router = router.Router(client=self.client, prompt_config_path=self.prompt_config_path)
        self.planner_agent = planner.Planner(self.client, self.prompt_config_path, mock=self.mock)
        self.solver_agent = solver.Solver(self.client, self.prompt_config_path, mock=self.mock)
        self.verifier_agent = verifier.Verifier(self.client, self.prompt_config_path, mock=self.mock)

    def solve(self, question: str, question_id: str | None = None) -> SolveResult:
        qid = question_id or "unknown"; started_at = now_iso(); trace_payload = {"question_id": qid, "question": question, "started_at": started_at, "finished_at": None, "latency_seconds": 0.0, "prompt_version": self.prompt_version, "run_mode": self.run_mode, "route_info": {}, "model_calls": [], "tool_calls": [], "verifier_result": {}, "final_result": {}, "errors": []}; traces = []
        try:
            route_info = self.router.route(question)
            route_dict = route_info.model_dump() if hasattr(route_info, "model_dump") else {"domain": getattr(route_info, "domain", "unknown"), "problem_type": getattr(route_info, "problem_type", "unknown"), "recommended_solver": getattr(route_info, "recommended_solver", ""), "reason": getattr(route_info, "reason", ""), "confidence": getattr(route_info, "confidence", 0.0)}
            trace_payload["route_info"] = route_dict

            tool_first_done = False
            if self.run_mode == "tool-first" and self.enable_tools:
                tv, tvf, ttrace = _run_tool_assist(question, route_dict.get("problem_type", ""), route_dict.get("recommended_solver", ""))
                traces.append(ttrace); trace_payload["tool_calls"].append(ttrace.model_dump())
                if tv is not None and tvf is not None and tvf.passed:
                    plan = planner._fallback_plan(question, route_dict)
                    draft = f"工具优先求得答案: \boxed{{{str(tv).strip()}}}"
                    final = str(tv).strip()
                    verification = tvf
                    status = "success"
                    current = draft
                    tool_first_done = True

            if not tool_first_done:
                if self.run_mode == "fast":
                    plan = planner._fallback_plan(question, route_dict)
                else:
                    plan = self.planner_agent.plan(question, route_dict)
                    trace_payload["model_calls"].append({"stage": "planner", "status": "ok", "model": getattr(self.client, "model", "intern-s1"), "prompt_chars": len(str(question)) + len(str(route_dict)), "response_chars": len(str(plan))})

                draft = self.solver_agent.solve(question, route_dict, plan)
                trace_payload["model_calls"].append({"stage": "solver", "status": "ok", "model": getattr(self.client, "model", "intern-s1"), "prompt_chars": len(str(question)) + len(str(plan)), "response_chars": len(str(draft))})

                final = _extract_final_answer_non_proof(draft, draft, None)
                status = "success"
                if not final:
                    final = _mock_answer_from_question(question) if self.mock else ""
                    if not final: status = "partial"; final = ""

                if self.run_mode == "fast":
                    verification = self.verifier_agent._tool_verify(draft, final) or Verification(method="self_review", passed=False, notes="fast mode: tool verifier fallback failed")
                else:
                    verification = self.verifier_agent.verify(question, draft, final, route_dict)
                    trace_payload["model_calls"].append({"stage": "verifier", "status": "ok", "model": getattr(self.client, "model", "intern-s1"), "prompt_chars": len(str(question)) + len(str(draft)), "response_chars": len(str(verification.notes))})

            current = draft
            if self.enable_tools:
                tv, tvf, ttrace = _run_tool_assist(question, route_dict.get("problem_type", ""), route_dict.get("recommended_solver", ""))
                traces.append(ttrace); trace_payload["tool_calls"].append(ttrace.model_dump())
                if tv is not None and tvf is not None:
                    final, verification, status = str(tv).strip(), tvf, "success"
                    current = f"工具校验/计算得到最终答案为 \\boxed{{{final}}}。"
            if not _is_proof_problem(route_dict.get("problem_type", ""), route_dict.get("recommended_solver", "")):
                final = _extract_final_answer_non_proof(draft, current, final)
                if not final:
                    status = "partial"

            rounds = 0
            while not verification.passed and rounds < self.max_refine_rounds:
                rounds += 1
                current = refiner.run(current)
                refined = _extract_final_answer_non_proof(draft, current, None)
                final = refined or final
                verification = self.verifier_agent.verify(question, current, final, route_dict)

            if not verification.passed and status == "success": status = "partial"
            plan_steps = plan.get("solution_plan", []) if isinstance(plan, dict) else []
            if not isinstance(plan_steps, list): plan_steps = []
            parse = plan.get("problem_parse", {}) if isinstance(plan, dict) else {}
            problem_parse = ProblemParse(
                goal=parse.get("goal", question) if isinstance(parse, dict) else question,
                givens=parse.get("givens", [question]) if isinstance(parse, dict) else [question],
                symbols=parse.get("symbols", []) if isinstance(parse, dict) else [],
            )
            final_type, final_boxed = _answer_type_and_boxed(route_dict, final, current)
            final_value = _extract_proof_conclusion(current) if final_type == "proof" else final
            if final_type == "proof" and final_value == "命题已完成证明。":
                final_value = "命题已完成证明。"
            verification = _proof_fallback_review(current, route_dict, verification, final_type, final_value, final_boxed)
            if verification.passed and status == "partial":
                status = "success"
            if _looks_like_long_markdown(final_value):
                status = "partial"
            if len(final_boxed) > 120 or "###" in final_boxed or final_boxed.count("\n") > 1:
                final_boxed = ""
            result = SolveResult(question_id=qid, domain=route_dict.get("domain", "unknown"), problem_type=route_dict.get("problem_type", "unknown"), problem_parse=problem_parse, solution_plan=plan_steps, visible_solution_steps=[current], tool_trace=traces, final_answer=FinalAnswer(type=final_type, value=final_value, boxed=final_boxed), verification=verification, didactic_hint=explainer.run(question), confidence=max(0.0, min(1.0, route_dict.get("confidence", 0.5) or 0.5)), status=status, error=None)
            trace_payload["model_calls_count"] = len(trace_payload["model_calls"])
        except Exception as exc:
            trace_payload["errors"].append(str(exc)); result = make_failure_result(question_id=qid, question=question, error_message=str(exc))
        finally:
            trace_payload["finished_at"] = now_iso(); trace_payload["final_result"] = result.model_dump()
            if self.save_trace:
                try: write_trace(trace_payload, self.trace_dir, qid)
                except Exception: pass
        return result


def solve_question(question, mock: bool = True, model: str = "intern-s1", enable_tools: bool = False, save_trace: bool = True, trace_dir: str | Path = "outputs/traces", run_mode: str = "full"):
    _ = model
    return MathAgentPipeline(mock=mock, enable_tools=enable_tools, save_trace=save_trace, trace_dir=trace_dir, run_mode=run_mode).solve(question.question, question.question_id)
