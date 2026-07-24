from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 1_100_000
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
CPU_LIMIT_SECONDS = 30


def _apply_posix_limits() -> None:
    if os.name == "nt":
        return
    try:
        import resource

        setrlimit = getattr(resource, "setrlimit", None)
        rlimit_as = getattr(resource, "RLIMIT_AS", None)
        rlimit_cpu = getattr(resource, "RLIMIT_CPU", None)
        if not callable(setrlimit) or rlimit_as is None or rlimit_cpu is None:
            raise RuntimeError("resource isolation is unavailable")
        setrlimit(rlimit_as, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
        setrlimit(rlimit_cpu, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS))
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError("resource isolation is unavailable") from exc


def main() -> int:
    _apply_posix_limits()
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        return 2
    source_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(source_root))
    from math_agent.io_utils import strict_json_loads

    try:
        request = strict_json_loads(raw.decode("utf-8", errors="strict"))
    except (RecursionError, TypeError, UnicodeError, ValueError):
        return 2
    if not isinstance(request, dict):
        return 2

    from math_agent.clients.interns1_client import _perform_http_request

    response: dict[str, Any] = _perform_http_request(request)
    encoded = json.dumps(
        response,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
