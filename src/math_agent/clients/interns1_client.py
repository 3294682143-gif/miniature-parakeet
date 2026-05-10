from __future__ import annotations

import os
import time
from typing import Any

import requests


class InternS1Client:
    DEFAULT_MODEL = "intern-s1"
    MOCK_RESPONSE = "[MOCK] Intern-S1 stable response"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None, timeout: int = 60, max_retries: int = 2, mock: bool = False) -> None:
        self.api_key = api_key or os.getenv("INTERNS1_API_KEY")
        self.base_url = base_url or os.getenv("INTERNS1_BASE_URL")
        self.model = model or os.getenv("INTERNS1_MODEL") or self.DEFAULT_MODEL
        self.timeout = timeout
        self.max_retries = max_retries
        self.mock = mock

    def _build_chat_completions_url(self) -> str:
        if not self.base_url:
            raise ValueError("missing_base_url: INTERNS1_BASE_URL is required in --real mode")
        normalized = self.base_url.rstrip("/")
        return normalized if normalized.endswith("/chat/completions") else f"{normalized}/chat/completions"

    def _validate_real_mode_config(self) -> None:
        if not self.api_key:
            raise ValueError("missing_api_key: INTERNS1_API_KEY is required in --real mode")
        if not self.base_url:
            raise ValueError("missing_base_url: INTERNS1_BASE_URL is required in --real mode")

    def chat(self, messages: list[dict[str, Any]], temperature: float = 0.2, top_p: float = 0.9, max_tokens: int = 4096) -> str:
        if self.mock:
            return self.MOCK_RESPONSE
        self._validate_real_mode_config()
        url = self._build_chat_completions_url()
        payload = {"model": self.model, "messages": messages, "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        attempts = max(1, self.max_retries)
        for attempt in range(1, attempts + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code in {401, 403}:
                    raise ValueError("auth_error: unauthorized (401/403)")
                if resp.status_code == 429:
                    raise ValueError("rate_limit: HTTP 429")
                if 500 <= resp.status_code < 600:
                    if attempt < attempts:
                        time.sleep(0.1)
                        continue
                    raise ValueError(f"server_error: HTTP {resp.status_code}")
                if 400 <= resp.status_code < 500:
                    raise ValueError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                return str(data["choices"][0]["message"]["content"])
            except requests.Timeout as exc:
                if attempt >= attempts:
                    raise ValueError("timeout: request timed out") from exc
            except requests.RequestException as exc:
                if attempt >= attempts:
                    raise ValueError("unknown_error: network request failed") from exc
            except ValueError:
                raise
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError("invalid_response: response JSON is not chat-completions compatible") from exc
        raise ValueError("unknown_error: request failed after retries")
