from __future__ import annotations

from dotenv import load_dotenv

from math_agent.clients.interns1_client import InternS1Client


def classify_error(exc: Exception) -> str:
    msg = str(exc)
    for key in ["missing_api_key", "missing_base_url", "auth_error", "rate_limit", "timeout", "server_error", "invalid_response", "unknown_error"]:
        if key in msg:
            return key
    return "unknown_error"


def main() -> int:
    load_dotenv(override=False)
    client = InternS1Client(mock=False)
    messages = [
        {"role": "system", "content": "你是数学助手。"},
        {"role": "user", "content": "计算 1+1，只输出答案。"},
    ]
    try:
        text = client.chat(messages)
        print({"ok": True, "model": client.model, "preview": text[:200]})
        return 0
    except Exception as exc:
        print({"ok": False, "error_type": classify_error(exc), "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
