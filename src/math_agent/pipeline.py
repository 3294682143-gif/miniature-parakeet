from __future__ import annotations

import re
import time
from contextvars import ContextVar
from decimal import Decimal
from hashlib import sha256
from math import gcd, isqrt
from pathlib import Path
from typing import Any, Literal, cast

from .agents import explainer, planner, refiner, router, solver, verifier
from .clients.interns1_client import InternS1Client
from .control.candidate_budget import (
    build_candidate_budget_plan,
    candidate_budget_plan_to_metadata,
)
from .control.hard_mode import HardModePolicy, policy_to_metadata
from .control.pipeline_hook import build_runtime_config, runtime_config_to_metadata
from .control.proof_guardian_hook import (
    build_proof_guardian_runtime_plan,
    proof_guardian_runtime_plan_to_metadata,
)
from .control.verifier_routing import (
    build_verifier_routing_plan,
    verifier_routing_plan_to_metadata,
)
from .control.weighted_voting_hook import (
    build_weighted_voting_runtime_plan,
    runtime_plan_to_metadata,
)
from .harness.formatter_repair import detect_dirty_final_answer, repair_solve_result
from .logging_utils import now_iso, write_trace
from .prompting import freeze_prompts, load_prompts_snapshot
from .schemas import (
    EXECUTION_PROFILE_VERSION,
    FinalAnswer,
    ProblemParse,
    SolveResult,
    ToolTrace,
    Verification,
    execution_provenance_fingerprint,
    make_failure_result,
    question_fingerprint,
)
from .security import safe_exception_text
from .tools import sympy_tools
from .tools.answer_normalizer import (
    extract_answer_by_patterns,
    extract_boxed_answer,
    extract_boxed_answers,
    normalize_answer,
)
from .tools.python_sandbox import evaluate_arithmetic_expression
from .typing import ChatClient
from .verification.verifier_scoring import score_candidates, score_to_metadata
from .verification.weighted_voting import decision_to_metadata, weighted_vote

_FINAL_ANSWER_TYPES = {"number", "expression", "set", "proof", "algorithm", "text"}
_SOLVE_STATUSES = {"success", "partial", "fail"}
_MAX_TOOL_QUESTION_CHARS = 4_096
_MAX_TOOL_INTEGER_ABS = 10**18
_MAX_FACTORIZATION_INPUT = 10**10

FinalAnswerType = Literal["number", "expression", "set", "proof", "algorithm", "text"]
SolveStatus = Literal["success", "partial", "fail"]
ToolName = Literal["python", "sympy", "none"]
VerificationMethod = Literal[
    "symbolic_check",
    "numeric_check",
    "substitution",
    "logic_review",
    "self_review",
    "none",
]

_MODEL_CALL_SINK: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "math_agent_model_call_sink", default=None
)


class _StageTracingClient:
    """Record only actual client.chat invocations without retaining prompt content."""

    def __init__(self, delegate: ChatClient, stage: str) -> None:
        self._delegate = delegate
        self._stage = stage

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def chat(self, messages: list[dict[str, Any]], *args: Any, **kwargs: Any) -> str:
        model_value = getattr(self._delegate, "model", "")
        model = (
            model_value
            if isinstance(model_value, str) and model_value
            else "unspecified"
        )
        prompt_chars = sum(
            len(message.get("content", ""))
            for message in messages
            if isinstance(message, dict) and isinstance(message.get("content", ""), str)
        )
        sink = _MODEL_CALL_SINK.get()
        try:
            response = self._delegate.chat(messages, *args, **kwargs)
        except Exception:
            if sink is not None:
                sink.append(
                    {
                        "stage": self._stage,
                        "status": "error",
                        "model": model,
                        "prompt_chars": prompt_chars,
                        "response_chars": 0,
                    }
                )
            raise
        if sink is not None:
            sink.append(
                {
                    "stage": self._stage,
                    "status": "ok",
                    "model": model,
                    "prompt_chars": prompt_chars,
                    "response_chars": len(str(response)),
                }
            )
        return response


def _eval_safe_math_expr(expr: str):
    return evaluate_arithmetic_expression(expr)


def _mock_answer_from_question(question: str) -> str | None:
    try:
        expression = _extract_simple_arithmetic(question)
        return str(_eval_safe_math_expr(expression)) if expression is not None else None
    except Exception:
        return None


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
    return (problem_type or "").lower() == "proof" or (
        recommended_solver or ""
    ).lower() == "proof"


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
        return normalized in {
            "结论",
            "最终结论",
            "结论：",
            "最终结论：",
            "已证明",
            "已证明：",
        }

    if not text:
        return "命题已完成证明。"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lead_patterns = [
        r"^最终结论\s*[:：]\s*(.+)$",
        r"^结论\s*[:：]\s*(.+)$",
        r"^已证明\s*[:：]?\s*(.+)$",
        r"^(?:final conclusion|conclusion)\s*[:：]\s*(.+)$",
        r"^(?:therefore|hence|thus|so|we conclude)\s*[,，:]?\s*(.+)$",
        r"^(?:proved|qed)\s*[:：]?\s*(.+)$",
    ]
    for i, line in enumerate(lines):
        line_for_match = _clean_markdown(line)
        if _is_header_shell(line_for_match):
            for follow in lines[i + 1 :]:
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

    for line in reversed(lines):
        line_for_match = _clean_markdown(line)
        m = re.search(
            r"(?:therefore|hence|thus|so|we conclude)\s*[,，:]?\s*(.+)",
            line_for_match,
            flags=re.I,
        )
        if m:
            candidate = _clean_markdown(m.group(1))
            if _is_meaningful(candidate):
                return f"Proved: {candidate}"

    if re.search(
        r"\b(assume|suppose|therefore|hence|thus|qed|contradiction|prove|proof)\b",
        text,
        flags=re.I,
    ):
        for line in reversed(lines):
            candidate = _clean_markdown(line)
            if _is_meaningful(candidate):
                return f"Proved: {candidate}"

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
    # Proof-shape heuristics are diagnostic evidence, not a substitute verifier.
    # In particular, a failed/non-JSON verifier response must remain failed so
    # keyword-rich but mathematically false prose cannot become a success.
    _ = (current_steps, route_dict, final_type, final_value, final_boxed)
    return verification


def _answer_type_and_boxed(
    route_dict: dict, final_value: str, current_steps: str
) -> tuple[str, str]:
    ptype = (route_dict.get("problem_type", "") or "").lower()
    solver_name = (route_dict.get("recommended_solver", "") or "").lower()
    if _is_proof_problem(ptype, solver_name):
        value = _extract_proof_conclusion(current_steps)
        if (
            not value.startswith("已证明")
            and not value.lower().startswith("proved")
            and "命题已完成证明" not in value
        ):
            value = f"已证明：{value}"
        return "proof", ""
    if ptype == "calculation":
        inferred_type = _infer_answer_type(final_value)
        if inferred_type == "text":
            inferred_type = "expression"
    else:
        inferred_type = (
            ptype
            if ptype in {"number", "expression", "set", "algorithm", "text"}
            else _infer_answer_type(final_value)
        )
    if inferred_type in {"number", "expression", "set"} and _is_short_clean_answer(
        final_value
    ):
        boxed = f"\\boxed{{{final_value}}}"
        if len(boxed) <= 120 and "###" not in boxed and boxed.count("\n") <= 1:
            return inferred_type, boxed
    if inferred_type in {"algorithm", "text"}:
        return inferred_type, ""
    return inferred_type, ""


def _extract_final_answer_non_proof(
    draft: str, current: str, tv: str | None = None
) -> str:
    for candidate in [
        _extract_multiple_boxed_answer(current),
        _extract_multiple_boxed_answer(draft),
    ]:
        if candidate:
            return candidate
    for candidate in [extract_boxed_answer(current), extract_boxed_answer(draft)]:
        if candidate:
            return candidate
    for candidate in [
        extract_answer_by_patterns(current),
        extract_answer_by_patterns(draft),
    ]:
        if candidate and _is_short_clean_answer(candidate):
            return candidate
    if tv is not None:
        tvs = str(tv).strip()
        if _is_short_clean_answer(tvs):
            return normalize_answer(tvs)
    for candidate in [current, draft]:
        normalized = normalize_answer(str(candidate or ""))
        lower = normalized.lower()
        if (
            _is_short_clean_answer(normalized)
            and not _looks_like_long_markdown(normalized)
            and not any(
                token in lower
                for token in ["answer is", "final answer", "question", "plan"]
            )
            and bool(
                re.search(
                    (
                        r"(\d|=|\+|-|\*|/|\[|\]|\(|\)|\bpi\b|\bx\b|\bsin\b|"
                        r"\bcos\b|\btan\b|\blog\b)"
                    ),
                    lower,
                )
            )
        ):
            return normalized
    return ""


def _extract_multiple_boxed_answer(text: str) -> str | None:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    scopes: list[str] = []
    for line in reversed(lines):
        if re.search(r"(final\s*answer|answer\s*:|final_answer|答案|最终)", line, re.I):
            scopes.append(line)
            break
    if not scopes and len(lines) == 1:
        scopes.append(lines[0])
    for scope in scopes:
        boxes = [
            normalize_answer(value)
            for value in extract_boxed_answers(scope)
            if _is_short_clean_answer(value)
        ]
        boxes = [value for value in boxes if value]
        if len(boxes) >= 2:
            return "[" + ",".join(boxes) + "]"
    return None


def _looks_like_long_markdown(text: str) -> bool:
    value = (text or "").strip()
    return len(value) > 300 and (
        "###" in value or value.count("\n\n") >= 1 or value.count("\n") > 2
    )


def _tool_success(
    value: str,
    method: VerificationMethod,
    notes: str,
    purpose: str,
    tool: ToolName = "sympy",
) -> tuple[str, Verification, ToolTrace]:
    rendered = str(value).strip()
    if (
        not rendered
        or rendered in {"[]", "{}"}
        or re.search(r"(?:^|[^a-z])(?:zoo|oo|nan|[+-]?inf)(?:$|[^a-z])", rendered, re.I)
    ):
        raise ValueError("tool result is outside the supported finite domain")
    normalized = normalize_answer(rendered)
    if not normalized:
        raise ValueError("tool result could not be normalized safely")
    return (
        normalized,
        Verification(method=method, passed=True, notes=notes),
        ToolTrace(tool=tool, purpose=purpose, status="success", summary=rendered),
    )


def _sentence_without_final_only(question: str) -> str:
    return re.sub(r"\bgive the final answer only\.?", "", question, flags=re.I).strip()


def _extract_simple_arithmetic(question: str) -> str | None:
    text = _sentence_without_final_only(str(question)).strip()
    text = text.replace("计算", "").strip()
    prefix = re.match(
        r"^(?:compute|calculate|evaluate|what\s+is)\s+(.+?)\s*[?!.]?\s*$",
        text,
        flags=re.I,
    )
    if prefix is not None:
        text = prefix.group(1).strip()
    else:
        text = text.rstrip(" ?!").strip()
    text = re.sub(r"\s*=\s*$", "", text).strip()
    if not re.fullmatch(r"[\d\s+\-*/().^]+", text) or not re.search(r"\d", text):
        return None
    return text.replace("^", "**")


def _extract_requested_equation(question: str) -> str | None:
    text = _sentence_without_final_only(str(question)).strip().rstrip("?!. ")
    text = re.sub(
        r"^(?:please\s+)?solve(?:\s+the\s+equation)?\s*[:：]?\s*",
        "",
        text,
        count=1,
        flags=re.I,
    )
    for prefix in ("求解方程", "解方程", "求解"):
        if text.startswith(prefix):
            text = text[len(prefix) :].lstrip(" :：")
            break
    if text.count("=") != 1 or not re.fullmatch(
        r"[0-9A-Za-z().+\-*/^\s]+=[0-9A-Za-z().+\-*/^\s]+", text
    ):
        return None
    allowed_functions = {
        "abs",
        "acos",
        "asin",
        "atan",
        "cos",
        "cosh",
        "exp",
        "ln",
        "log",
        "sin",
        "sinh",
        "sqrt",
        "tan",
        "tanh",
    }
    identifiers = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
    if any(
        len(name) != 1 and name.casefold() not in allowed_functions
        for name in identifiers
    ):
        return None
    return text


def _has_multiple_tool_targets(question: str) -> bool:
    target_patterns = (
        r"\bgcd\s*\(",
        r"\blcm\s*\(",
        r"\b\d+\s+choose\s+\d+\b",
        r"\b(?:derivative|differentiate|integral|integrate)\b",
        r"\b(?:euler\s+phi|phi)\b",
        r"\b(?:multiplicative\s+inverse|least\s+positive\s+inverse)\b",
        r"\b(?:least\s+nonnegative\s+residue|remainder\s+when)\b",
        r"\b\d+(?:\.\d+)?\s*[+*/-]\s*\d+(?:\.\d+)?\b",
    )
    return (
        sum(
            sum(1 for _ in re.finditer(pattern, question, flags=re.I))
            for pattern in target_patterns
        )
        > 1
    )


def _integer_power_exponent(base: str, value: str) -> str | None:
    if (
        re.fullmatch(r"[+-]?\d+", base) is None
        or re.fullmatch(r"[+-]?\d+", value) is None
    ):
        return None
    try:
        b = int(base)
        v = int(value)
    except ValueError:
        return None
    if abs(b) > _MAX_TOOL_INTEGER_ABS or abs(v) > _MAX_TOOL_INTEGER_ABS:
        return None
    if b in {0, 1} or v == 0:
        return None
    current = 1
    for exponent in range(0, 64):
        if current == v:
            return str(exponent)
        current *= b
    return None


def _parse_tool_int(value: str, *, max_abs: int = _MAX_TOOL_INTEGER_ABS) -> int:
    if len(value.strip().lstrip("-")) > 19:
        raise ValueError("tool integer is too large")
    parsed = int(value)
    if abs(parsed) > max_abs:
        raise ValueError("tool integer is too large")
    return parsed


def _factor_int(n: int) -> dict[int, int]:
    if not 1 <= n <= _MAX_FACTORIZATION_INPUT:
        raise ValueError("factorization input is outside the safe range")
    factors: dict[int, int] = {}
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors[d] = factors.get(d, 0) + 1
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        factors[n] = factors.get(n, 0) + 1
    return factors


def _totient(n: int) -> int:
    result = n
    for p in _factor_int(n):
        result = result // p * (p - 1)
    return result


def _divisor_count(n: int) -> int:
    count = 1
    for exp in _factor_int(n).values():
        count *= exp + 1
    return count


def _format_sqrt_int(n: int) -> str:
    if not 0 <= n <= _MAX_FACTORIZATION_INPUT:
        raise ValueError("square-root simplification input is outside the safe range")
    root = isqrt(n)
    if root * root == n:
        return str(root)
    outside = 1
    inside = n
    factor = 2
    while factor * factor <= inside:
        sq = factor * factor
        while inside % sq == 0:
            outside *= factor
            inside //= sq
        factor += 1
    if outside == 1:
        return f"sqrt({inside})"
    if inside == 1:
        return str(outside)
    return f"{outside}*sqrt({inside})"


def _crt_two(a: int, m: int, b: int, n: int) -> int | None:
    if not (0 < m <= _MAX_TOOL_INTEGER_ABS and 0 < n <= _MAX_TOOL_INTEGER_ABS):
        raise ValueError("CRT modulus is outside the safe range")
    common = gcd(m, n)
    difference = b - a
    if difference % common:
        return None
    reduced_m = m // common
    reduced_n = n // common
    multiplier = 0
    if reduced_n != 1:
        multiplier = (difference // common) * pow(reduced_m, -1, reduced_n)
        multiplier %= reduced_n
    modulus = reduced_m * n
    return (a + m * multiplier) % modulus


def _run_tool_assist(
    question: str, problem_type: str, recommended_solver: str
) -> tuple[str | None, Verification | None, ToolTrace]:
    q = question.strip()
    if len(q) > _MAX_TOOL_QUESTION_CHARS:
        return (
            None,
            None,
            ToolTrace(
                tool="none",
                purpose="tool assist",
                status="skipped",
                summary="question exceeds the tool-assist size limit",
            ),
        )
    try:
        short_q = _sentence_without_final_only(q)
        lower_q = short_q.lower()
        if _has_multiple_tool_targets(short_q):
            return (
                None,
                None,
                ToolTrace(
                    tool="none",
                    purpose="tool assist",
                    status="skipped",
                    summary="multiple mathematical targets require model review",
                ),
            )

        derivative_match = re.search(
            r"derivative of (?:f\(x\)\s*=\s*)?(.+?)(?:\.|$)",
            short_q,
            flags=re.I,
        )
        if "derivative" in lower_q and derivative_match:
            s = sympy_tools.differentiate_expression(derivative_match.group(1).strip())
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "symbolic_check",
                    "sympy derivative passed",
                    "differentiate expression",
                )

        limit_match = re.search(
            r"limit\s+as\s+([a-zA-Z])\s+approaches\s+([^\s]+)\s+of\s+(.+?)(?:\.|$)",
            short_q,
            flags=re.I,
        )
        if limit_match:
            var, point, expr = limit_match.groups()
            s = sympy_tools.limit_expression(expr.strip(), var, point)
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s, "symbolic_check", "sympy limit passed", "compute limit"
                )

        integral_match = re.search(
            (
                r"definite integral of (.+?) from ([a-zA-Z])\s*=\s*([^\s]+)"
                r"\s+to\s+\2\s*=\s*([^\s.]+)"
            ),
            short_q,
            flags=re.I,
        )
        if integral_match:
            expr, var, lower, upper = integral_match.groups()
            s = sympy_tools.integrate_expression(expr.strip(), var, lower, upper)
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "symbolic_check",
                    "sympy definite integral passed",
                    "compute definite integral",
                )

        decimal_pattern = r"(?:\d+(?:\.\d+)?|\.\d+)"
        log_match = re.search(
            rf"log\s+base\s+({decimal_pattern})\s+of\s+({decimal_pattern})",
            short_q,
            flags=re.I,
        )
        if log_match:
            base, value = log_match.groups()
            base_decimal, value_decimal = Decimal(base), Decimal(value)
            if base_decimal <= 0 or base_decimal == 1 or value_decimal <= 0:
                raise ValueError("logarithm inputs are outside the real domain")
            s = _integer_power_exponent(base, value) or sympy_tools.solve_equation(
                f"{base}**x={value}"
            )
            if isinstance(s, str) and s.startswith("x="):
                s = s.split("=", 1)[1]
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s, "numeric_check", "sympy log passed", "compute logarithm"
                )

        exponential_match = re.search(
            rf"exponential equation\s+({decimal_pattern})\*\*x\s*=\s*({decimal_pattern})",
            short_q,
            flags=re.I,
        )
        if exponential_match:
            base, value = exponential_match.groups()
            s = _integer_power_exponent(base, value) or sympy_tools.solve_equation(
                f"{base}**x={value}"
            )
            if isinstance(s, str) and s.startswith("x="):
                s = s.split("=", 1)[1]
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "sympy exponential solve passed",
                    "solve exponential equation",
                )

        choose_match = re.search(r"\b(\d+)\s+choose\s+(\d+)\b", short_q, flags=re.I)
        if choose_match:
            s = sympy_tools.choose(*choose_match.groups())
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "combination formula passed",
                    "compute combination",
                )

        gcd_match = re.search(r"\bgcd\((\d+)\s*,\s*(\d+)\)", short_q, flags=re.I)
        if gcd_match:
            a, b = (_parse_tool_int(x) for x in gcd_match.groups())
            return _tool_success(
                str(gcd(a, b)), "numeric_check", "gcd passed", "compute gcd"
            )

        lcm_match = re.search(r"\blcm\((\d+)\s*,\s*(\d+)\)", short_q, flags=re.I)
        if lcm_match:
            a, b = (_parse_tool_int(x) for x in lcm_match.groups())
            value = abs(a * b) // gcd(a, b) if a and b else 0
            return _tool_success(
                str(value), "numeric_check", "lcm passed", "compute lcm"
            )

        remainder_match = re.search(
            r"remainder\s+when\s+(\d+)\s+is\s+divided\s+by\s+(\d+)",
            short_q,
            flags=re.I,
        )
        if remainder_match:
            a, b = (_parse_tool_int(x) for x in remainder_match.groups())
            return _tool_success(
                str(a % b),
                "numeric_check",
                "modular arithmetic passed",
                "compute remainder",
            )

        modpow_match = re.search(
            (
                r"(?:least nonnegative residue|remainder)\s+of\s+(\d+)\s*\^\s*"
                r"(\d+)\s+(?:modulo|mod)\s+(\d+)"
            ),
            short_q,
            flags=re.I,
        )
        if modpow_match:
            base, exponent, modulus = (
                _parse_tool_int(x) for x in modpow_match.groups()
            )
            return _tool_success(
                str(pow(base, exponent, modulus)),
                "numeric_check",
                "modular exponentiation passed",
                "compute modular exponent",
            )

        phi_match = re.search(
            r"(?:euler phi|phi)\s*(?:\(|of\s+)(\d+)\)?", short_q, flags=re.I
        )
        if phi_match:
            return _tool_success(
                str(
                    _totient(
                        _parse_tool_int(
                            phi_match.group(1), max_abs=_MAX_FACTORIZATION_INPUT
                        )
                    )
                ),
                "numeric_check",
                "totient formula passed",
                "compute euler phi",
            )

        divisor_match = re.search(
            r"how many positive divisors does\s+(\d+)\s+have", short_q, flags=re.I
        )
        if divisor_match:
            return _tool_success(
                str(
                    _divisor_count(
                        _parse_tool_int(
                            divisor_match.group(1), max_abs=_MAX_FACTORIZATION_INPUT
                        )
                    )
                ),
                "numeric_check",
                "divisor-count formula passed",
                "count positive divisors",
            )

        inverse_match = re.search(
            (
                r"(?:least positive inverse|multiplicative inverse)\s+of\s+(\d+)"
                r"\s+(?:modulo|mod)\s+(\d+)"
            ),
            short_q,
            flags=re.I,
        )
        if inverse_match:
            a, modulus = (_parse_tool_int(x) for x in inverse_match.groups())
            return _tool_success(
                str(pow(a, -1, modulus)),
                "numeric_check",
                "modular inverse passed",
                "compute modular inverse",
            )

        ascii_crt_match = re.search(
            (
                r"x\s*(?:=|is\s+congruent\s+to)\s*(-?\d+)\s*(?:mod|modulo)"
                r"\s*(\d+).*x\s*(?:=|is\s+congruent\s+to)\s*(-?\d+)"
                r"\s*(?:mod|modulo)\s*(\d+)"
            ),
            short_q,
            flags=re.I,
        )
        if ascii_crt_match and "least nonnegative" in lower_q:
            a, m, b, n = (_parse_tool_int(x) for x in ascii_crt_match.groups())
            value = _crt_two(a, m, b, n)
            if value is not None:
                return _tool_success(
                    str(value),
                    "numeric_check",
                    "crt search passed",
                    "solve two-congruence CRT",
                )

        crt_match = re.search(
            (
                r"x\s*(?:\u2261|=)\s*(-?\d+)\s*(?:mod|modulo)\s*(\d+).*"
                r"x\s*(?:\u2261|=)\s*(-?\d+)\s*(?:mod|modulo)\s*(\d+)"
            ),
            short_q,
            flags=re.I,
        )
        if crt_match and "least nonnegative" in lower_q:
            a, m, b, n = (_parse_tool_int(x) for x in crt_match.groups())
            value = _crt_two(a, m, b, n)
            if value is not None:
                return _tool_success(
                    str(value),
                    "numeric_check",
                    "crt search passed",
                    "solve two-congruence CRT",
                )

        slope_match = re.search(
            (
                r"through\s*\((-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\)"
                r"\s*and\s*\((-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\)"
            ),
            short_q,
            flags=re.I,
        )
        if "slope" in lower_q and slope_match:
            x1, y1, x2, y2 = slope_match.groups()
            if Decimal(x1) == Decimal(x2):
                raise ValueError("vertical line has no finite slope")
            s = sympy_tools.simplify_expression(f"(({y2})-({y1}))/(({x2})-({x1}))")
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s, "numeric_check", "slope formula passed", "compute slope"
                )

        distance_sq_match = re.search(
            (
                r"squared distance between\s*\((-?\d+),\s*(-?\d+)\)\s*and"
                r"\s*\((-?\d+),\s*(-?\d+)\)"
            ),
            short_q,
            flags=re.I,
        )
        if distance_sq_match:
            x1, y1, x2, y2 = (_parse_tool_int(x) for x in distance_sq_match.groups())
            return _tool_success(
                str((x2 - x1) ** 2 + (y2 - y1) ** 2),
                "numeric_check",
                "squared distance formula passed",
                "compute squared distance",
            )

        y_intercept_match = re.search(
            r"y-intercept of y\s*=\s*(.+?)(?:\.|$)", short_q, flags=re.I
        )
        if y_intercept_match:
            s = sympy_tools.limit_expression(
                y_intercept_match.group(1).strip(), "x", "0"
            )
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "y-intercept evaluation passed",
                    "compute y-intercept",
                )

        vertex_match = re.search(
            r"vertex x-coordinate of y\s*=\s*(.+?)(?:\.|$)", short_q, flags=re.I
        )
        if vertex_match:
            derivative = sympy_tools.differentiate_expression(
                vertex_match.group(1).strip()
            )
            s = sympy_tools.solve_equation(f"{derivative}=0")
            if s.startswith("x="):
                s = s.split("=", 1)[1]
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "symbolic_check",
                    "vertex derivative check passed",
                    "compute vertex x-coordinate",
                )

        rect_match = re.search(
            r"rectangle.*length\s+([0-9.]+).*width\s+([0-9.]+).*area",
            short_q,
            flags=re.I,
        )
        if rect_match:
            length, width = rect_match.groups()
            if Decimal(length) <= 0 or Decimal(width) <= 0:
                raise ValueError("rectangle dimensions must be positive")
            s = sympy_tools.simplify_expression(f"{length}*{width}")
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "rectangle area formula passed",
                    "compute rectangle area",
                )

        triangle_match = re.search(
            r"triangle.*base\s+([0-9.]+).*height\s+([0-9.]+).*area",
            short_q,
            flags=re.I,
        )
        if triangle_match:
            base, height = triangle_match.groups()
            if Decimal(base) <= 0 or Decimal(height) <= 0:
                raise ValueError("triangle dimensions must be positive")
            s = sympy_tools.simplify_expression(f"({base})*({height})/2")
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "triangle area formula passed",
                    "compute triangle area",
                )

        right_inradius_match = re.search(
            r"right triangle has legs\s+(\d+)\s+and\s+(\d+).*inradius",
            short_q,
            flags=re.I,
        )
        if right_inradius_match:
            a, b = (_parse_tool_int(x) for x in right_inradius_match.groups())
            if a <= 0 or b <= 0:
                raise ValueError("triangle legs must be positive")
            c_sq = a * a + b * b
            c = isqrt(c_sq)
            if c * c == c_sq:
                s = sympy_tools.simplify_expression(f"({a}+{b}-{c})/2")
                if not s.startswith("ERROR:"):
                    return _tool_success(
                        s,
                        "numeric_check",
                        "right-triangle inradius formula passed",
                        "compute right triangle inradius",
                    )

        heron_match = re.search(
            r"triangle has side lengths\s+(\d+),\s*(\d+),\s*(\d+).*area",
            short_q,
            flags=re.I,
        )
        if heron_match:
            a, b, c = (_parse_tool_int(x) for x in heron_match.groups())
            s2 = a + b + c
            area_sq_num = s2 * (s2 - 2 * a) * (s2 - 2 * b) * (s2 - 2 * c)
            if area_sq_num > 0 and area_sq_num % 16 == 0:
                return _tool_success(
                    _format_sqrt_int(area_sq_num // 16),
                    "numeric_check",
                    "heron formula passed",
                    "compute triangle area by sides",
                )

        chord_match = re.search(
            r"circle has radius\s+(\d+).*chord is\s+(\d+)\s+from the center.*length",
            short_q,
            flags=re.I,
        )
        if chord_match:
            radius, distance = (_parse_tool_int(x) for x in chord_match.groups())
            inner = radius * radius - distance * distance
            if radius > 0 and 0 <= distance < radius and inner > 0:
                root = _format_sqrt_int(inner)
                value = str(2 * int(root)) if root.isdigit() else f"2*{root}"
                return _tool_success(
                    value,
                    "symbolic_check",
                    "chord-length formula passed",
                    "compute circle chord length",
                )

        circle_match = re.search(
            r"circle.*radius\s+([0-9]+(?:\.[0-9]+)?).*area", short_q, flags=re.I
        )
        if circle_match:
            radius_text = circle_match.group(1)
            if Decimal(radius_text) <= 0:
                raise ValueError("circle radius must be positive")
            s = sympy_tools.simplify_expression(f"({radius_text})**2*pi")
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "symbolic_check",
                    "circle area formula passed",
                    "compute circle area",
                )

        coin_match = re.search(
            r"coin is tossed\s+(\d+)\s+times.*exactly\s+(\d+)\s+heads",
            short_q,
            flags=re.I,
        )
        if coin_match:
            trials_text, heads_text = coin_match.groups()
            s = sympy_tools.simplify_expression(
                f"{sympy_tools.choose(trials_text, heads_text)}/2**{trials_text}"
            )
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "binomial probability passed",
                    "compute binomial probability",
                )

        mean_match = re.search(
            r"numbers?\s+([0-9,\s.-]+)\s+have.*mean", short_q, flags=re.I
        )
        if mean_match:
            nums = [x for x in re.split(r"[,\s]+", mean_match.group(1).strip()) if x]
            if nums:
                s = sympy_tools.simplify_expression(f"({' + '.join(nums)})/{len(nums)}")
                if not s.startswith("ERROR:"):
                    return _tool_success(
                        s,
                        "numeric_check",
                        "arithmetic mean passed",
                        "compute arithmetic mean",
                    )

        sequence_match = re.search(
            r"a_n\s*=\s*(.+?),?\s*compute\s+a_(\d+)", short_q, flags=re.I
        )
        if sequence_match:
            expr, index = sequence_match.groups()
            s = sympy_tools.simplify_expression(expr.strip().replace("n", index))
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "sequence substitution passed",
                    "compute sequence term",
                )

        arithmetic_sequence_match = re.search(
            (
                r"arithmetic sequence has a_1\s*=\s*(-?\d+).*common "
                r"difference\s+(-?\d+).*a_(\d+)"
            ),
            short_q,
            flags=re.I,
        )
        if arithmetic_sequence_match:
            first, diff, index = (
                _parse_tool_int(x) for x in arithmetic_sequence_match.groups()
            )
            return _tool_success(
                str(first + (index - 1) * diff),
                "numeric_check",
                "arithmetic sequence formula passed",
                "compute arithmetic sequence term",
            )

        geometric_sequence_match = re.search(
            r"geometric sequence has a_1\s*=\s*(-?\d+).*ratio\s+(-?\d+).*a_(\d+)",
            short_q,
            flags=re.I,
        )
        if geometric_sequence_match:
            first, ratio, index = (
                _parse_tool_int(x) for x in geometric_sequence_match.groups()
            )
            if not 1 <= index <= 1_001:
                raise ValueError("geometric sequence index is outside the safe range")
            return _tool_success(
                str(
                    evaluate_arithmetic_expression(
                        f"({first})*(({ratio})**({index - 1}))"
                    )
                ),
                "numeric_check",
                "geometric sequence formula passed",
                "compute geometric sequence term",
            )

        function_eval_match = re.search(
            r"if f\(x\)\s*=\s*(.+?),\s*compute f\((-?\d+)\)",
            short_q,
            flags=re.I,
        )
        if function_eval_match:
            expr, x_value = function_eval_match.groups()
            s = sympy_tools.simplify_expression(expr.replace("x", f"({x_value})"))
            if not s.startswith("ERROR:"):
                return _tool_success(
                    s,
                    "numeric_check",
                    "function evaluation passed",
                    "compute function value",
                )

        composition_match = re.search(
            (
                r"if f\(x\)\s*=\s*(.+?)\s+and g\(x\)\s*=\s*(.+?),"
                r"\s*compute f\(g\((-?\d+)\)\)"
            ),
            short_q,
            flags=re.I,
        )
        if composition_match:
            f_expr, g_expr, x_value = composition_match.groups()
            g_value = sympy_tools.simplify_expression(
                g_expr.replace("x", f"({x_value})")
            )
            if not g_value.startswith("ERROR:"):
                s = sympy_tools.simplify_expression(f_expr.replace("x", f"({g_value})"))
                if not s.startswith("ERROR:"):
                    return _tool_success(
                        s,
                        "numeric_check",
                        "function composition passed",
                        "compute function composition",
                    )

        equation = _extract_requested_equation(q)
        if "化简" in q:
            expr = q.split("化简", 1)[1].strip(" ：:？?")
            s = sympy_tools.simplify_expression(expr)
            if not s.startswith("ERROR:"):
                return (
                    s,
                    Verification(
                        method="symbolic_check",
                        passed=True,
                        notes="sympy simplify passed",
                    ),
                    ToolTrace(
                        tool="sympy",
                        purpose="simplify expression",
                        status="success",
                        summary=s,
                    ),
                )
        if equation and (
            "求解" in q or "解方程" in q or q.lower().startswith("solve") or "解 " in q
        ):
            s = sympy_tools.solve_equation(equation)
            if not s.startswith("ERROR:"):
                return (
                    s,
                    Verification(
                        method="substitution", passed=True, notes="sympy solve passed"
                    ),
                    ToolTrace(
                        tool="sympy",
                        purpose="solve equation",
                        status="success",
                        summary=s,
                    ),
                )
        maybe = _extract_simple_arithmetic(q)
        if maybe is not None and (
            problem_type == "calculation"
            or (recommended_solver or "").lower() == "program"
            or re.fullmatch(r"[\d\s\+\-\*/\(\)\.\^]+", maybe)
        ):
            v = str(_eval_safe_math_expr(maybe))
            return (
                v,
                Verification(
                    method="numeric_check",
                    passed=True,
                    notes="safe arithmetic eval passed",
                ),
                ToolTrace(
                    tool="python", purpose="arithmetic", status="success", summary=v
                ),
            )
    except Exception as exc:
        return (
            None,
            None,
            ToolTrace(
                tool="python",
                purpose="tool assist",
                status="fail",
                summary=safe_exception_text(exc),
            ),
        )
    return (
        None,
        None,
        ToolTrace(
            tool="none", purpose="tool assist", status="skipped", summary="fallback"
        ),
    )


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


class MathAgentPipeline:
    def __init__(
        self,
        client: ChatClient | None = None,
        prompt_config_path: str | Path = "configs/prompts.yaml",
        mock: bool = True,
        enable_tools: bool = False,
        max_refine_rounds: int = 1,
        save_trace: bool = True,
        trace_dir: str | Path = "outputs/traces",
        prompt_version: str = "default",
        run_mode: str = "full",
        hard_mode_policy: HardModePolicy | None = None,
    ) -> None:
        if run_mode not in {"full", "fast", "tool-first"}:
            raise ValueError("run_mode must be one of: full, fast, tool-first")
        self.mock = mock
        self.enable_tools = enable_tools
        if (
            isinstance(max_refine_rounds, bool)
            or not isinstance(max_refine_rounds, int)
            or not 0 <= max_refine_rounds <= 3
        ):
            raise ValueError("max_refine_rounds must be an integer between 0 and 3")
        self.max_refine_rounds = max_refine_rounds
        self.save_trace = save_trace
        self.trace_dir = Path(trace_dir)
        self.prompt_version = prompt_version
        self.run_mode = run_mode
        self.hard_mode_policy = hard_mode_policy
        self.client = client or InternS1Client(mock=mock)
        self.prompt_config_path = Path(prompt_config_path)
        prompt_snapshot, self._prompt_config_digest = load_prompts_snapshot(
            self.prompt_config_path
        )
        self._prompt_snapshot = freeze_prompts(prompt_snapshot)
        self.router = router.Router(
            client=_StageTracingClient(self.client, "router"),
            prompt_config_path=self.prompt_config_path,
            prompts=self._prompt_snapshot,
        )
        self.planner_agent = planner.Planner(
            _StageTracingClient(self.client, "planner"),
            self.prompt_config_path,
            mock=self.mock,
            prompts=self._prompt_snapshot,
        )
        self.solver_agent = solver.Solver(
            _StageTracingClient(self.client, "solver"),
            self.prompt_config_path,
            mock=self.mock,
            prompts=self._prompt_snapshot,
        )
        self.verifier_agent = verifier.Verifier(
            _StageTracingClient(self.client, "verifier"),
            self.prompt_config_path,
            mock=self.mock,
            prompts=self._prompt_snapshot,
        )
        self.refiner_agent = refiner.Refiner(
            _StageTracingClient(self.client, "refiner"),
            self.prompt_config_path,
            mock=self.mock,
            prompts=self._prompt_snapshot,
        )

    def execution_profile(self) -> dict[str, Any]:
        client_class = (
            f"{type(self.client).__module__}.{type(self.client).__qualname__}"
        )
        hard_mode = (
            policy_to_metadata(self.hard_mode_policy)
            if self.hard_mode_policy is not None
            else None
        )
        endpoint_sha256 = ""
        if not self.mock:
            endpoint_value = getattr(self.client, "base_url", "")
            if isinstance(endpoint_value, str) and endpoint_value:
                endpoint_sha256 = sha256(
                    endpoint_value.encode("utf-8", errors="strict")
                ).hexdigest()
        trace_dir_sha256 = ""
        if self.save_trace:
            trace_dir_sha256 = sha256(
                str(self.trace_dir.absolute()).encode("utf-8", errors="strict")
            ).hexdigest()
        timeout_value = getattr(self.client, "timeout", None)
        timeout = (
            timeout_value
            if isinstance(timeout_value, int)
            and not isinstance(timeout_value, bool)
            and timeout_value > 0
            else None
        )
        retries_value = getattr(self.client, "max_retries", None)
        max_retries = (
            retries_value
            if isinstance(retries_value, int)
            and not isinstance(retries_value, bool)
            and retries_value > 0
            else None
        )
        profile: dict[str, Any] = {
            "profile_version": EXECUTION_PROFILE_VERSION,
            "schema": "SolveResult/v2",
            "client_class": client_class,
            "mock": self.mock,
            "model": _as_str(getattr(self.client, "model", ""), "") or "unspecified",
            "endpoint_sha256": endpoint_sha256,
            "timeout": timeout,
            "max_retries": max_retries,
            "enable_tools": self.enable_tools,
            "save_trace": self.save_trace,
            "trace_dir_sha256": trace_dir_sha256,
            "run_mode": self.run_mode,
            "max_refine_rounds": self.max_refine_rounds,
            "prompt_version": self.prompt_version,
            "prompt_config_sha256": self._prompt_config_digest,
            "hard_mode_policy": hard_mode,
        }
        return profile

    def execution_fingerprint(self, question: str) -> str:
        return execution_provenance_fingerprint(
            question=question, execution_profile=self.execution_profile()
        )

    def _verify_tool_candidate(
        self,
        question: str,
        value: str,
        route_info: dict[str, Any],
        diagnostic: Verification,
    ) -> Verification:
        if diagnostic.passed is not True:
            return diagnostic
        if self.mock:
            return diagnostic
        independent = self.verifier_agent.verify(
            question,
            f"Independent tool candidate: {value}",
            value,
            route_info,
        )
        if not independent.passed:
            return independent
        return Verification(
            method=independent.method,
            passed=True,
            notes=(f"Independent verifier passed. Tool diagnostic: {diagnostic.notes}"),
        )

    def solve(self, question: str, question_id: str | None = None) -> SolveResult:
        qid = question_id or "unknown"
        execution_fingerprint = ""
        started_at = now_iso()
        started_perf = time.perf_counter()
        plan: dict[str, Any] = {}
        draft: str = ""
        current: str = ""
        final: str = ""
        status: str = "partial"
        verification = Verification(method="none", passed=False, notes="not verified")
        traces: list[ToolTrace] = []
        result = make_failure_result(
            question_id=qid,
            question=question,
            error_message="pipeline not executed",
        )
        model_calls: list[dict[str, Any]] = []
        trace_payload: dict[str, Any] = {
            "question_id": qid,
            "question": question,
            "started_at": started_at,
            "finished_at": None,
            "latency_seconds": 0.0,
            "prompt_version": self.prompt_version,
            "run_mode": self.run_mode,
            "route_info": {},
            "model_calls": model_calls,
            "tool_calls": [],
            "verifier_result": {},
            "final_result": {},
            "errors": [],
        }
        trace_metadata: dict[str, Any]
        if self.mock:
            trace_metadata = {
                "mock_evaluation_only": True,
                "mock_results_are_not_official": True,
            }
        else:
            trace_metadata = {"real_execution_requested": True}
        trace_payload["metadata"] = trace_metadata
        if self.hard_mode_policy is not None:
            answer_type_hint = (
                "proof"
                if any(
                    tok in question.lower()
                    for tok in ["证明", "prove", "show that", "证"]
                )
                else "text"
            )
            runtime_config = build_runtime_config(
                self.hard_mode_policy,
                no_trace=not self.save_trace,
                answer_type=answer_type_hint,
                max_candidate_budget=3,
            )
            policy_snapshot = policy_to_metadata(self.hard_mode_policy)
            trace_metadata.update(
                {
                    "hard_mode_policy": policy_snapshot,
                    "hard_mode_runtime": runtime_config_to_metadata(runtime_config),
                    "hard_mode_enabled": self.hard_mode_policy.enabled,
                    "hard_mode_level": self.hard_mode_policy.level,
                    "hard_mode_effect": runtime_config.effect,
                    "hard_mode_candidate_budget_preview": (
                        runtime_config.effective_candidate_budget
                    ),
                    "hard_mode_verifier_level_preview": runtime_config.verifier_level,
                }
            )
            if runtime_config.enabled:
                candidate_budget_plan = build_candidate_budget_plan(runtime_config)
                verifier_routing_plan = build_verifier_routing_plan(
                    runtime_config,
                    answer_type=answer_type_hint,
                )
                trace_metadata["candidate_budget_plan"] = (
                    candidate_budget_plan_to_metadata(candidate_budget_plan)
                )
                trace_metadata["verifier_routing_plan"] = (
                    verifier_routing_plan_to_metadata(verifier_routing_plan)
                )
                weighted_plan = build_weighted_voting_runtime_plan(
                    runtime_config,
                    candidate_budget_plan,
                    verifier_routing_plan,
                    current_answer="",
                    answer_type=answer_type_hint,
                )
                trace_metadata["weighted_voting_plan"] = runtime_plan_to_metadata(
                    weighted_plan
                )
                trace_metadata["weighted_voting_effect"] = "preview_only"
                _candidates = [
                    {
                        "candidate_id": "candidate-0",
                        "source": "solver",
                        "final_answer_value": "",
                    }
                ]
                _scores = score_candidates(
                    _candidates,
                    verifier_level=weighted_plan.verifier_level,
                    answer_type=answer_type_hint,
                )
                _decision = weighted_vote(_candidates, _scores)
                trace_metadata["verifier_scores"] = [
                    score_to_metadata(x) for x in _scores
                ]
                trace_metadata["weighted_vote_decision"] = decision_to_metadata(
                    _decision
                )
                proof_plan = build_proof_guardian_runtime_plan(
                    runtime_config,
                    verifier_routing_plan,
                    current_answer={"final_answer_value": ""},
                    answer_type=answer_type_hint,
                )
                if proof_plan.enabled:
                    trace_metadata["proof_guardian_plan"] = (
                        proof_guardian_runtime_plan_to_metadata(proof_plan)
                    )
                    trace_metadata["proof_guardian_effect"] = "preview_only"
                trace_metadata["hard_mode_execution_effect"] = (
                    "candidate_and_verifier_routing_preview"
                )
        model_call_token = _MODEL_CALL_SINK.set(model_calls)
        try:
            execution_profile = self.execution_profile()
            execution_fingerprint = execution_provenance_fingerprint(
                question=question, execution_profile=execution_profile
            )
            result = result.model_copy(
                update={"execution_fingerprint": execution_fingerprint}
            )
            trace_payload["input_fingerprint"] = result.input_fingerprint
            trace_payload["execution_fingerprint"] = execution_fingerprint
            trace_payload["execution_profile"] = execution_profile
            route_info = self.router.route(question)
            route_dict = (
                route_info.model_dump()
                if hasattr(route_info, "model_dump")
                else {
                    "domain": getattr(route_info, "domain", "unknown"),
                    "problem_type": getattr(route_info, "problem_type", "unknown"),
                    "recommended_solver": getattr(route_info, "recommended_solver", ""),
                    "reason": getattr(route_info, "reason", ""),
                    "confidence": getattr(route_info, "confidence", 0.0),
                }
            )
            trace_payload["route_info"] = route_dict

            tool_first_done = False
            tool_first_attempted = False
            if self.run_mode == "tool-first" and self.enable_tools:
                tool_first_attempted = True
                problem_type = _as_str(route_dict.get("problem_type", ""), "")
                recommended_solver = _as_str(
                    route_dict.get("recommended_solver", ""), ""
                )
                tv, tvf, ttrace = _run_tool_assist(
                    question,
                    problem_type,
                    recommended_solver,
                )
                traces.append(ttrace)
                tool_calls = trace_payload.get("tool_calls")
                if isinstance(tool_calls, list):
                    tool_calls.append(ttrace.model_dump())
                if (
                    tv is not None
                    and tvf is not None
                    and tvf.passed is True
                    and ttrace.status == "success"
                ):
                    tool_verification = self._verify_tool_candidate(
                        question, str(tv).strip(), route_dict, tvf
                    )
                else:
                    tool_verification = None
                if tool_verification is not None and tool_verification.passed:
                    plan = planner._fallback_plan(question, route_dict)
                    draft = f"工具优先求得答案: \\boxed{{{str(tv).strip()}}}"
                    final = str(tv).strip()
                    verification = tool_verification
                    status = "success"
                    current = draft
                    tool_first_done = True

            if not tool_first_done:
                if self.run_mode == "fast":
                    plan = planner._fallback_plan(question, route_dict)
                else:
                    plan = self.planner_agent.plan(question, route_dict)

                draft = self.solver_agent.solve(question, route_dict, plan)

                deterministic_mock_answer = (
                    _mock_answer_from_question(question) if self.mock else None
                )
                if deterministic_mock_answer is not None:
                    draft = (
                        "Deterministic local mock calculation: "
                        f"\\boxed{{{deterministic_mock_answer}}}"
                    )

                final = _extract_final_answer_non_proof(draft, draft, None)
                status = "success"
                if not final:
                    mock_final = (
                        _mock_answer_from_question(question) if self.mock else ""
                    )
                    if mock_final:
                        final = mock_final
                    else:
                        status = "partial"
                        final = ""

                verification = self.verifier_agent.verify(
                    question, draft, final, route_dict
                )
                if self.mock and deterministic_mock_answer is None:
                    verification = Verification(
                        method="none",
                        passed=False,
                        notes=(
                            "Mock mode cannot certify questions without a successful "
                            "bounded deterministic check."
                        ),
                    )

            current = draft
            if self.enable_tools and not tool_first_done and not tool_first_attempted:
                problem_type = _as_str(route_dict.get("problem_type", ""), "")
                recommended_solver = _as_str(
                    route_dict.get("recommended_solver", ""), ""
                )
                tv, tvf, ttrace = _run_tool_assist(
                    question,
                    problem_type,
                    recommended_solver,
                )
                traces.append(ttrace)
                tool_calls = trace_payload.get("tool_calls")
                if isinstance(tool_calls, list):
                    tool_calls.append(ttrace.model_dump())
                if (
                    tv is not None
                    and tvf is not None
                    and tvf.passed is True
                    and ttrace.status == "success"
                ):
                    tool_verification = self._verify_tool_candidate(
                        question, str(tv).strip(), route_dict, tvf
                    )
                else:
                    tool_verification = None
                if tool_verification is not None and tool_verification.passed:
                    final, verification, status = (
                        str(tv).strip(),
                        tool_verification,
                        "success",
                    )
                    current = f"工具校验/计算得到最终答案为 \\boxed{{{final}}}。"
            if not _is_proof_problem(
                _as_str(route_dict.get("problem_type", ""), ""),
                _as_str(route_dict.get("recommended_solver", ""), ""),
            ):
                final = _extract_final_answer_non_proof(draft, current, final)
                if not final:
                    status = "partial"

            rounds = 0
            while not verification.passed and rounds < self.max_refine_rounds:
                rounds += 1
                previous = current
                current = self.refiner_agent.refine(
                    question, current, verification.model_dump()
                )
                if not isinstance(current, str) or current == previous:
                    current = previous
                    break
                refined = _extract_final_answer_non_proof(current, current, None)
                final = refined or final
                verification = self.verifier_agent.verify(
                    question, current, final, route_dict
                )

            if not verification.passed and status == "success":
                status = "partial"
            plan_steps = plan.get("solution_plan", []) if isinstance(plan, dict) else []
            if not isinstance(plan_steps, list):
                plan_steps = []
            parse = plan.get("problem_parse", {}) if isinstance(plan, dict) else {}
            problem_parse = ProblemParse(
                goal=(
                    parse.get("goal", question) if isinstance(parse, dict) else question
                ),
                givens=(
                    parse.get("givens", [question])
                    if isinstance(parse, dict)
                    else [question]
                ),
                symbols=parse.get("symbols", []) if isinstance(parse, dict) else [],
            )
            final_type, final_boxed = _answer_type_and_boxed(route_dict, final, current)
            final_value = (
                _extract_proof_conclusion(current) if final_type == "proof" else final
            )
            if final_type == "proof" and final_value == "命题已完成证明。":
                final_value = "命题已完成证明。"
            verification = _proof_fallback_review(
                current, route_dict, verification, final_type, final_value, final_boxed
            )
            if verification.passed and status == "partial":
                status = "success"
            if _looks_like_long_markdown(final_value):
                status = "partial"
            if (
                len(final_boxed) > 120
                or "###" in final_boxed
                or final_boxed.count("\n") > 1
            ):
                final_boxed = ""
            final_answer_type = cast(
                FinalAnswerType,
                final_type if final_type in _FINAL_ANSWER_TYPES else "text",
            )
            solve_status = cast(
                SolveStatus, status if status in _SOLVE_STATUSES else "partial"
            )
            result = SolveResult(
                question_id=qid,
                domain=_as_str(route_dict.get("domain", "unknown"), "unknown"),
                problem_type=_as_str(
                    route_dict.get("problem_type", "unknown"), "unknown"
                ),
                problem_parse=problem_parse,
                solution_plan=plan_steps,
                visible_solution_steps=[current],
                tool_trace=traces,
                final_answer=FinalAnswer(
                    type=final_answer_type, value=final_value, boxed=final_boxed
                ),
                verification=verification,
                didactic_hint=explainer.run(question),
                confidence=max(
                    0.0, min(1.0, _as_float(route_dict.get("confidence", 0.5), 0.5))
                ),
                status=solve_status,
                error=None,
                input_fingerprint=question_fingerprint(question),
                execution_fingerprint=execution_fingerprint,
            )
            pre_flags = detect_dirty_final_answer(result)
            repaired = repair_solve_result(result)
            post_flags = detect_dirty_final_answer(repaired)
            risk_flags = sorted(set(pre_flags + post_flags))
            changed = repaired.model_dump() != result.model_dump()
            if changed and risk_flags and repaired.final_answer.type != "proof":
                repaired = repaired.model_copy(
                    update={
                        "verification": repaired.verification.model_copy(
                            update={
                                "notes": (
                                    f"{repaired.verification.notes} | "
                                    f"formatter_risk_flags={risk_flags}"
                                )
                            }
                        )
                    }
                )
                trace_payload.setdefault("verification_issues", []).extend(risk_flags)
            result = repaired
        except Exception as exc:
            trace_payload["errors"].append(safe_exception_text(exc))
            result = make_failure_result(
                question_id=qid,
                question=question,
                error_message=safe_exception_text(exc),
                execution_fingerprint=execution_fingerprint,
            )
        finally:
            trace_payload["finished_at"] = now_iso()
            trace_payload["latency_seconds"] = time.perf_counter() - started_perf
            trace_payload["input_fingerprint"] = result.input_fingerprint
            trace_payload["execution_fingerprint"] = result.execution_fingerprint
            trace_payload["model_calls_count"] = len(model_calls)
            route_result = trace_payload.get("route_info")
            if not isinstance(route_result, dict):
                route_result = {}
                trace_payload["route_info"] = route_result
            route_result["domain"] = result.domain
            route_result["problem_type"] = result.problem_type
            trace_payload["verifier_result"] = result.verification.model_dump()
            trace_payload["final_result"] = result.model_dump()
            if self.save_trace:
                try:
                    write_trace(trace_payload, self.trace_dir, qid)
                except Exception as exc:
                    trace_error = f"trace_write_failed: {safe_exception_text(exc)}"
                    result = result.model_copy(
                        update={
                            "status": "fail",
                            "error": trace_error,
                            "verification": Verification(
                                method="none",
                                passed=False,
                                notes="Required trace persistence failed.",
                            ),
                        }
                    )
            _MODEL_CALL_SINK.reset(model_call_token)
        return result


def execution_fingerprint_for_question(
    question,
    mock: bool = True,
    model: str | None = None,
    enable_tools: bool = False,
    save_trace: bool = True,
    trace_dir: str | Path = "outputs/traces",
    run_mode: str = "full",
    hard_mode_policy: HardModePolicy | None = None,
    prompt_config_path: str | Path = "configs/prompts.yaml",
    prompt_version: str = "default",
    max_refine_rounds: int = 1,
) -> str:
    client = InternS1Client(mock=mock, model=model)
    pipeline = MathAgentPipeline(
        client=client,
        prompt_config_path=prompt_config_path,
        mock=mock,
        enable_tools=enable_tools,
        max_refine_rounds=max_refine_rounds,
        save_trace=save_trace,
        trace_dir=trace_dir,
        prompt_version=prompt_version,
        run_mode=run_mode,
        hard_mode_policy=hard_mode_policy,
    )
    return pipeline.execution_fingerprint(question.question)


def solve_question(
    question,
    mock: bool = True,
    model: str | None = None,
    enable_tools: bool = False,
    save_trace: bool = True,
    trace_dir: str | Path = "outputs/traces",
    run_mode: str = "full",
    hard_mode_policy: HardModePolicy | None = None,
):
    client = InternS1Client(mock=mock, model=model)
    return MathAgentPipeline(
        client=client,
        mock=mock,
        enable_tools=enable_tools,
        save_trace=save_trace,
        trace_dir=trace_dir,
        run_mode=run_mode,
        hard_mode_policy=hard_mode_policy,
    ).solve(question.question, question.question_id)
