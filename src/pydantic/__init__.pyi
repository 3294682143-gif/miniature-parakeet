from __future__ import annotations

from typing import Any, Callable, TypeVar

MISSING: Any

class ValidationError(Exception): ...

_T = TypeVar("_T", bound="BaseModel")

def Field(
    default: Any = ...,
    *,
    default_factory: Callable[[], Any] | Any = ...,
    **_ignored_constraints: Any,
) -> Any: ...

class BaseModel:
    def __init__(self, **data: Any) -> None: ...
    @classmethod
    def model_validate(cls: type[_T], data: dict[str, Any]) -> _T: ...
    def model_dump(self) -> dict[str, Any]: ...
    def model_dump_json(self, ensure_ascii: bool = True) -> str: ...
    def model_copy(self: _T, *, update: dict[str, Any] | None = None) -> _T: ...
