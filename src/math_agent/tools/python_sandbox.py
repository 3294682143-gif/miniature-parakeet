from __future__ import annotations

import ast
import json
import math
import operator
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from math_agent.io_utils import strict_json_loads
from math_agent.process_isolation import ProcessCapacityError, isolated_process_slot
from math_agent.security import safe_exception_text

MAX_CODE_LENGTH = 4_096
MAX_AST_NODES = 256
MAX_STATEMENTS = 64
MAX_OUTPUT_CHARS = 8_192
MAX_COLLECTION_ITEMS = 1_024
MAX_TOTAL_VALUE_ITEMS = 4_096
MAX_VALUE_DEPTH = 8
MAX_INTEGER_BITS = 4_096
MAX_ABS_EXPONENT = 1_000
MAX_TIMEOUT_SECONDS = 30
WORKER_STATUSES = {"blocked", "error", "success", "timeout"}


class SandboxPolicyError(ValueError):
    """Raised when code is outside the deterministic safe subset."""


_ALLOWED_AST_TYPES = (
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.Name,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.List,
    ast.Tuple,
    ast.Load,
    ast.Store,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
)
_ALLOWED_CALLS = {"abs", "len", "max", "min", "pow", "print", "round", "sum"}
_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def _blocked(message: str = "Blocked by the safe Python policy.") -> dict[str, str]:
    return {
        "status": "blocked",
        "stdout": "",
        "stderr": message,
        "result_summary": "Unsupported or unsafe Python syntax.",
    }


def _consume_value_budget(
    budget: dict[str, int], *, items: int = 0, characters: int = 0
) -> None:
    budget["items"] += items
    if budget["items"] > MAX_TOTAL_VALUE_ITEMS:
        raise SandboxPolicyError("nested value has too many total items")
    budget["characters"] += characters
    if budget["characters"] > MAX_OUTPUT_CHARS:
        raise SandboxPolicyError("nested value is too large")


def _validate_value(
    value: Any,
    *,
    _depth: int = 0,
    _budget: dict[str, int] | None = None,
) -> Any:
    if _depth > MAX_VALUE_DEPTH:
        raise SandboxPolicyError("nested value is too deep")
    budget = _budget if _budget is not None else {"items": 0, "characters": 0}
    _consume_value_budget(budget, items=1)

    if isinstance(value, bool):
        _consume_value_budget(budget, characters=len(str(value)))
        return value
    if isinstance(value, int):
        if value.bit_length() > MAX_INTEGER_BITS:
            raise SandboxPolicyError("integer result is too large")
        _consume_value_budget(budget, characters=len(str(value)))
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SandboxPolicyError("non-finite numbers are not allowed")
        _consume_value_budget(budget, characters=len(str(value)))
        return value
    if isinstance(value, str):
        if len(value) > MAX_OUTPUT_CHARS:
            raise SandboxPolicyError("string value is too large")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise SandboxPolicyError("string is not valid UTF-8 text") from exc
        _consume_value_budget(budget, characters=len(value))
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise SandboxPolicyError("collection is too large")
        separator_characters = max(0, len(value) - 1) * 2
        _consume_value_budget(budget, characters=2 + separator_characters)
        for item in value:
            _validate_value(item, _depth=_depth + 1, _budget=budget)
        return value
    raise SandboxPolicyError(f"value type {type(value).__name__!r} is not allowed")


def _validate_program(code: str) -> ast.Module:
    if not isinstance(code, str):
        raise SandboxPolicyError("code must be a string")
    if not code.strip():
        raise SandboxPolicyError("code is empty")
    if len(code) > MAX_CODE_LENGTH:
        raise SandboxPolicyError("code is too long")
    try:
        tree = ast.parse(code, mode="exec")
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        raise SandboxPolicyError("code is not valid Python syntax") from exc

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise SandboxPolicyError("program has too many AST nodes")
    if len(tree.body) > MAX_STATEMENTS:
        raise SandboxPolicyError("program has too many statements")

    for node in nodes:
        if not isinstance(node, _ALLOWED_AST_TYPES):
            raise SandboxPolicyError(f"syntax {type(node).__name__!r} is not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise SandboxPolicyError("private names are not allowed")
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise SandboxPolicyError("only simple variable assignment is allowed")
            if node.targets[0].id in _ALLOWED_CALLS:
                raise SandboxPolicyError("safe function names cannot be reassigned")
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in _ALLOWED_CALLS
            ):
                raise SandboxPolicyError("function call is not in the allowlist")
            if node.keywords:
                raise SandboxPolicyError("keyword arguments are not allowed")
        if isinstance(node, ast.Constant):
            _validate_value(node.value)
    return tree


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _safe_power(left: Any, right: Any) -> Any:
    if not _is_number(left) or not _is_number(right):
        raise SandboxPolicyError("power operands must be numeric")
    if abs(right) > MAX_ABS_EXPONENT:
        raise SandboxPolicyError("power exponent is too large")
    if isinstance(left, int) and isinstance(right, int) and right >= 0:
        projected_bits = max(1, left.bit_length()) * max(1, right)
        if projected_bits > MAX_INTEGER_BITS:
            raise SandboxPolicyError("power result would be too large")
    return _validate_value(operator.pow(left, right))


def _safe_sequence_multiply(left: Any, right: Any) -> Any:
    sequence: str | list[Any] | tuple[Any, ...]
    multiplier: int
    if isinstance(left, (str, list, tuple)) and isinstance(right, int):
        sequence, multiplier = left, right
    elif isinstance(right, (str, list, tuple)) and isinstance(left, int):
        sequence, multiplier = right, left
    else:
        raise SandboxPolicyError("sequence multiplication requires an integer")
    projected_size = len(sequence) * max(0, multiplier)
    limit = MAX_OUTPUT_CHARS if isinstance(sequence, str) else MAX_COLLECTION_ITEMS
    if projected_size > limit:
        raise SandboxPolicyError("sequence result would be too large")
    return _validate_value(operator.mul(sequence, multiplier))


def _eval_binary(node: ast.BinOp, variables: dict[str, Any]) -> Any:
    left = _eval_expression(node.left, variables)
    right = _eval_expression(node.right, variables)
    if isinstance(node.op, ast.Pow):
        return _safe_power(left, right)
    if isinstance(node.op, ast.Mult) and (
        isinstance(left, (str, list, tuple)) or isinstance(right, (str, list, tuple))
    ):
        return _safe_sequence_multiply(left, right)
    if isinstance(node.op, ast.Add) and isinstance(left, (str, list, tuple)):
        if type(left) is not type(right):
            raise SandboxPolicyError("sequence addition requires matching types")
        return _validate_value(operator.add(left, right))
    if not _is_number(left) or not _is_number(right):
        raise SandboxPolicyError("arithmetic operands must be numeric")
    operation = _BINARY_OPERATORS.get(type(node.op))
    if operation is None:
        raise SandboxPolicyError("binary operator is not allowed")
    if (
        isinstance(node.op, ast.Mult)
        and isinstance(left, int)
        and isinstance(right, int)
    ):
        if left.bit_length() + right.bit_length() > MAX_INTEGER_BITS:
            raise SandboxPolicyError("integer result would be too large")
    return _validate_value(operation(left, right))


def _flatten_call_values(arguments: list[Any]) -> list[Any]:
    if len(arguments) == 1 and isinstance(arguments[0], (list, tuple)):
        return list(arguments[0])
    return arguments


def _eval_call(node: ast.Call, variables: dict[str, Any]) -> Any:
    if not isinstance(node.func, ast.Name):
        raise SandboxPolicyError("only direct safe function calls are allowed")
    name = node.func.id
    arguments = [_eval_expression(argument, variables) for argument in node.args]
    if name == "abs" and len(arguments) == 1 and _is_number(arguments[0]):
        return _validate_value(abs(arguments[0]))
    if (
        name == "len"
        and len(arguments) == 1
        and isinstance(arguments[0], (str, list, tuple))
    ):
        return len(arguments[0])
    if name in {"min", "max"}:
        values = _flatten_call_values(arguments)
        if not values or not all(_is_number(value) for value in values):
            raise SandboxPolicyError(f"{name} requires numeric values")
        return _validate_value(min(values) if name == "min" else max(values))
    if (
        name == "sum"
        and len(arguments) == 1
        and isinstance(arguments[0], (list, tuple))
    ):
        if not all(_is_number(value) for value in arguments[0]):
            raise SandboxPolicyError("sum requires numeric values")
        return _validate_value(sum(arguments[0]))
    if name == "pow" and len(arguments) == 2:
        return _safe_power(arguments[0], arguments[1])
    if name == "round" and len(arguments) in {1, 2}:
        if not _is_number(arguments[0]):
            raise SandboxPolicyError("round requires a numeric value")
        digits = arguments[1] if len(arguments) == 2 else None
        if digits is not None and (
            not isinstance(digits, int) or isinstance(digits, bool) or abs(digits) > 100
        ):
            raise SandboxPolicyError("round digits are out of range")
        return _validate_value(round(arguments[0], digits))
    if name == "print":
        raise SandboxPolicyError("print is only allowed as a top-level statement")
    raise SandboxPolicyError(f"invalid arguments for safe function {name!r}")


def _eval_expression(node: ast.expr, variables: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return _validate_value(node.value)
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise SandboxPolicyError(f"unknown variable {node.id!r}")
        return variables[node.id]
    if isinstance(node, ast.BinOp):
        return _eval_binary(node, variables)
    if isinstance(node, ast.UnaryOp):
        value = _eval_expression(node.operand, variables)
        if not _is_number(value):
            raise SandboxPolicyError("unary operators require numeric values")
        if isinstance(node.op, ast.UAdd):
            return _validate_value(operator.pos(value))
        if isinstance(node.op, ast.USub):
            return _validate_value(operator.neg(value))
        raise SandboxPolicyError("unary operator is not allowed")
    if isinstance(node, ast.List):
        return _validate_value(
            [_eval_expression(element, variables) for element in node.elts]
        )
    if isinstance(node, ast.Tuple):
        return _validate_value(
            tuple(_eval_expression(element, variables) for element in node.elts)
        )
    if isinstance(node, ast.Call):
        return _eval_call(node, variables)
    raise SandboxPolicyError(f"expression {type(node).__name__!r} is not allowed")


def _append_rendered(parts: list[str], budget: dict[str, int], text: str) -> None:
    budget["characters"] += len(text)
    if budget["characters"] > MAX_OUTPUT_CHARS:
        raise SandboxPolicyError("stdout limit exceeded")
    parts.append(text)


def _render_value(
    value: Any,
    parts: list[str],
    budget: dict[str, int],
    *,
    nested: bool = False,
    depth: int = 0,
) -> None:
    """Render an allowed value without materialising a whole nested repr."""

    if depth > MAX_VALUE_DEPTH:
        raise SandboxPolicyError("nested value is too deep")
    if isinstance(value, str):
        _append_rendered(parts, budget, repr(value) if nested else value)
        return
    if isinstance(value, (bool, int, float)):
        _append_rendered(parts, budget, str(value))
        return
    if isinstance(value, (list, tuple)):
        opening, closing = ("[", "]") if isinstance(value, list) else ("(", ")")
        _append_rendered(parts, budget, opening)
        for index, item in enumerate(value):
            if index:
                _append_rendered(parts, budget, ", ")
            _render_value(
                item,
                parts,
                budget,
                nested=True,
                depth=depth + 1,
            )
        if isinstance(value, tuple) and len(value) == 1:
            _append_rendered(parts, budget, ",")
        _append_rendered(parts, budget, closing)
        return
    raise SandboxPolicyError(f"value type {type(value).__name__!r} is not allowed")


def _execute_safe_program(code: str) -> str:
    tree = _validate_program(code)
    variables: dict[str, Any] = {}
    output_parts: list[str] = []
    output_budget = {"characters": 0}

    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            target = statement.targets[0]
            if not isinstance(target, ast.Name):
                raise SandboxPolicyError("assignment target is not allowed")
            variables[target.id] = _eval_expression(statement.value, variables)
            continue
        if not isinstance(statement, ast.Expr):
            raise SandboxPolicyError(
                f"statement {type(statement).__name__!r} is not allowed"
            )
        if isinstance(statement.value, ast.Call):
            call = statement.value
            if isinstance(call.func, ast.Name) and call.func.id == "print":
                values = [
                    _eval_expression(argument, variables) for argument in call.args
                ]
                for index, value in enumerate(values):
                    if index:
                        _append_rendered(output_parts, output_budget, " ")
                    _render_value(value, output_parts, output_budget)
                _append_rendered(output_parts, output_budget, "\n")
                continue
        _eval_expression(statement.value, variables)
    return "".join(output_parts)


def evaluate_arithmetic_expression(expression: str) -> int | float:
    """Evaluate one bounded arithmetic expression without starting a worker."""
    program = _validate_program(expression)
    if len(program.body) != 1 or not isinstance(program.body[0], ast.Expr):
        raise SandboxPolicyError("exactly one arithmetic expression is required")
    value = _eval_expression(program.body[0].value, {})
    value = _validate_value(value)
    if not _is_number(value):
        raise SandboxPolicyError("expression result must be numeric")
    return value


def _worker_result(code: str) -> dict[str, str]:
    try:
        stdout = _execute_safe_program(code)
        return {
            "status": "success",
            "stdout": stdout,
            "stderr": "",
            "result_summary": "Safe arithmetic program executed successfully.",
        }
    except SandboxPolicyError as exc:
        return _blocked(safe_exception_text(exc))
    except Exception as exc:
        return {
            "status": "error",
            "stdout": "",
            "stderr": safe_exception_text(exc),
            "result_summary": f"Execution error: {type(exc).__name__}",
        }


def _worker_main() -> int:
    code = sys.stdin.read(MAX_CODE_LENGTH + 1)
    result = _worker_result(code)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


def _invalid_worker_result() -> dict[str, str]:
    return {
        "status": "error",
        "stdout": "",
        "stderr": "Invalid result returned from sandbox worker.",
        "result_summary": "Sandbox execution failed.",
    }


def _run_python_code_without_capacity_guard(
    code: str, timeout_seconds: int = 5
) -> dict[str, str]:
    """Execute a deterministic arithmetic-only Python subset in a worker."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not (1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS)
    ):
        return _blocked("timeout_seconds is outside the allowed range")
    try:
        _validate_program(code)
    except SandboxPolicyError as exc:
        return _blocked(safe_exception_text(exc))

    worker_path = Path(__file__).resolve()
    command = [sys.executable, "-I", "-X", "utf8", str(worker_path), "--worker"]
    try:
        completed = subprocess.run(
            command,
            input=code,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "stdout": "",
            "stderr": "Execution exceeded the wall-clock limit.",
            "result_summary": f"Exceeded {timeout_seconds} seconds.",
        }
    except OSError as exc:
        return {
            "status": "error",
            "stdout": "",
            "stderr": safe_exception_text(exc),
            "result_summary": "Sandbox worker could not be started.",
        }

    if completed.returncode != 0:
        return _invalid_worker_result()
    try:
        result = strict_json_loads(completed.stdout)
    except (RecursionError, TypeError, ValueError):
        return _invalid_worker_result()
    expected_keys = {"status", "stdout", "stderr", "result_summary"}
    if (
        not isinstance(result, dict)
        or set(result) != expected_keys
        or not all(isinstance(result[key], str) for key in expected_keys)
        or result["status"] not in WORKER_STATUSES
    ):
        return _invalid_worker_result()
    return {
        "status": result["status"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "result_summary": result["result_summary"],
    }


def run_python_code(code: str, timeout_seconds: int = 5) -> dict[str, str]:
    """Execute code while enforcing the shared isolated-worker budget."""

    try:
        with isolated_process_slot():
            return _run_python_code_without_capacity_guard(code, timeout_seconds)
    except ProcessCapacityError:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "Isolated process capacity is exhausted.",
            "result_summary": "Sandbox worker capacity is exhausted.",
        }


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("This module is an internal sandbox worker.")
    raise SystemExit(_worker_main())
