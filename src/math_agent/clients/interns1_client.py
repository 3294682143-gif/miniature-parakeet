from __future__ import annotations

import os
import time
from typing import Any

import requests


class InternS1Client:
    """Intern-S1 API client with mock-first behavior and basic retries."""

    DEFAULT_MODEL = "intern-s1"
    MOCK_RESPONSE = "[MOCK] Intern-S1 stable response"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 60,
        max_retries: int = 2,
        mock: bool = False,
    ) -> None:
        self.api_key = api_key or os.getenv("INTERNS1_API_KEY")
        self.base_url = base_url or os.getenv("INTERNS1_BASE_URL")
        self.model = model or os.getenv("INTERNS1_MODEL") or self.DEFAULT_MODEL
        self.timeout = timeout
        self.max_retries = max_retries
        self.mock = mock

    def _build_chat_completions_url(self) -> str:
        if not self.base_url:
            raise ValueError("INTERNS1 base_url is required when mock=False")
        normalized = self.base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    def _validate_real_mode_config(self) -> None:
        if not self.api_key:
            raise ValueError("INTERNS1 api_key is required when mock=False")
        if not self.base_url:
            raise ValueError("INTERNS1 base_url is required when mock=False")

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        top_p: float = 0.9,
        max_tokens: int = 4096,
    ) -> str:
        if self.mock:
            return self.MOCK_RESPONSE

        self._validate_real_mode_config()
        url = self._build_chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }

        attempts = max(1, self.max_retries)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if 500 <= response.status_code < 600:
                    if attempt < attempts:
                        time.sleep(0.1)
                        continue
                    response.raise_for_status()
                if 400 <= response.status_code < 500:
                    response.raise_for_status()

                data = response.json()
                return str(data["choices"][0]["message"]["content"])
            except requests.HTTPError as exc:
                last_error = exc
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code is not None and 400 <= status_code < 500:
                    raise ValueError(f"InternS1 request failed with HTTP {status_code}") from exc
                if attempt >= attempts:
                    raise ValueError("InternS1 request failed after retries (server error)") from exc
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= attempts:
                    raise ValueError("InternS1 request failed after retries (network error)") from exc
                time.sleep(0.1)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError("InternS1 response format is invalid") from exc

        raise ValueError("InternS1 request failed") from last_error
