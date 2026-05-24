from __future__ import annotations

import json
from dataclasses import MISSING, asdict, dataclass
from dataclasses import field as dc_field
from dataclasses import replace as dc_replace
from typing import Any, cast


class ValidationError(Exception):
    pass


def Field(default=MISSING, default_factory=MISSING, **_ignored_constraints: Any):
    kwargs = {}
    if default is not MISSING:
        kwargs["default"] = default
    if default_factory is not MISSING:
        kwargs["default_factory"] = default_factory
    return dc_field(**kwargs)


class _BaseModelMeta(type):
    def __new__(mcls, name, bases, ns):
        cls = super().__new__(mcls, name, bases, ns)
        if name != "BaseModel":
            cls = dataclass(cls)  # type: ignore[arg-type]
        return cls


class BaseModel(metaclass=_BaseModelMeta):
    @classmethod
    def model_validate(cls, data: dict[str, Any]):
        return cls(**data)

    def model_dump(self) -> dict[str, Any]:
        return cast(dict[str, Any], asdict(cast(Any, self)))

    def model_dump_json(self, ensure_ascii: bool = True) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=ensure_ascii)

    def model_copy(self, *, update: dict[str, Any] | None = None):
        if not update:
            return dc_replace(cast(Any, self))
        return dc_replace(cast(Any, self), **update)
