from __future__ import annotations

from typing import Any, Protocol


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> str: ...
