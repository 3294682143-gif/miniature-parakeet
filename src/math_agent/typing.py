from __future__ import annotations

from typing import Any, Protocol


class ChatClient(Protocol):
    @property
    def model(self) -> str: ...

    def chat(
        self,
        messages: list[dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> str: ...
