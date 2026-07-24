from __future__ import annotations

import argparse
import json
from typing import Iterable

from dotenv import load_dotenv

if __package__ in {None, ""}:
    from _repo_bootstrap import prefer_repo_source

    prefer_repo_source()

from math_agent.clients.interns1_client import InternS1Client
from math_agent.security import safe_exception_text


def classify_error(exc: Exception) -> str:
    msg = safe_exception_text(exc)
    for key in [
        "missing_api_key",
        "missing_base_url",
        "missing_allowed_hosts",
        "invalid_allowed_hosts",
        "disallowed_host",
        "capacity_error",
        "auth_error",
        "rate_limit",
        "timeout",
        "server_error",
        "invalid_response",
        "unknown_error",
        "real_requires_allow_real",
    ]:
        if key in msg:
            return key
    return "unknown_error"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test the Intern-S1 client. Defaults to mock mode."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", default=True)
    mode.add_argument("--real", action="store_true", default=False)
    parser.add_argument(
        "--allow-real",
        action="store_true",
        default=False,
        help="Required together with --real to make an external API call.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.real and not args.allow_real:
        _print(
            {
                "ok": False,
                "mode": "real",
                "error_type": "real_requires_allow_real",
                "message": "Use --real --allow-real to run an external API smoke.",
            }
        )
        return 2

    mock = not args.real
    if args.real:
        load_dotenv(override=False)
    client = InternS1Client(mock=mock)
    messages = [
        {"role": "system", "content": "你是数学助手。"},
        {"role": "user", "content": "计算 1+1，只输出答案。"},
    ]
    try:
        text = client.chat(messages)
        _print(
            {
                "ok": True,
                "mode": "mock" if mock else "real",
                "model": client.model,
                "preview": text[:200],
            }
        )
        return 0
    except Exception as exc:
        message = safe_exception_text(exc)
        _print(
            {
                "ok": False,
                "mode": "mock" if mock else "real",
                "error_type": classify_error(exc),
                "message": message,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
