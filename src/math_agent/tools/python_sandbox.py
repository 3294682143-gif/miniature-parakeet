from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import re
_BLOCK_PATTERNS = [
    r"\bimport\s+os\b",
    r"\bimport\s+sys\b",
    r"\bimport\s+subprocess\b",
    r"\bimport\s+socket\b",
    r"\bimport\s+requests\b",
    r"\bpathlib\b",
    r"\bshutil\b",
    r"\bopen\s*\(",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"__import__",
    r"\bpip\b",
    r"\bcurl\b",
    r"\bwget\b",
]

_ALLOWED_IMPORTS = {"math", "fractions", "statistics", "sympy"}


def _is_blocked(code: str) -> bool:
    lowered = code.lower()
    return any(re.search(pattern, lowered) for pattern in _BLOCK_PATTERNS)


def _sandbox_worker(code: str, output: mp.Queue) -> None:
    safe_builtins = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "round": round,
        "range": range,
        "len": len,
        "print": print,
    }

    def _safe_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        root = name.split(".", 1)[0]
        if root not in _ALLOWED_IMPORTS:
            raise ImportError(f"blocked import: {name}")
        return __import__(name, globals, locals, fromlist, level)

    safe_builtins["__import__"] = _safe_import

    namespace = {"__builtins__": safe_builtins}
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(code, namespace, namespace)
        output.put(
            {
                "status": "success",
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
                "result_summary": "Code executed successfully.",
            }
        )
    except Exception as exc:
        output.put(
            {
                "status": "error",
                "stdout": stdout.getvalue(),
                "stderr": (stderr.getvalue() + str(exc)).strip(),
                "result_summary": f"Execution error: {type(exc).__name__}",
            }
        )


def run_python_code(code: str, timeout_seconds: int = 5) -> dict:
    if _is_blocked(code):
        return {
            "status": "blocked",
            "stdout": "",
            "stderr": "Blocked for security reasons.",
            "result_summary": "Dangerous pattern detected.",
        }

    queue: mp.Queue = mp.Queue()
    process = mp.Process(target=_sandbox_worker, args=(code, queue))
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        return {
            "status": "timeout",
            "stdout": "",
            "stderr": "Execution timed out.",
            "result_summary": f"Exceeded {timeout_seconds} seconds.",
        }

    if not queue.empty():
        result = queue.get()
        return result

    return {
        "status": "error",
        "stdout": "",
        "stderr": "No result returned from sandbox worker.",
        "result_summary": "Sandbox execution failed.",
    }
