from __future__ import annotations

import json
from dataclasses import MISSING, asdict, dataclass, field as dc_field, fields
from typing import Any


def Field(default=MISSING, default_factory=MISSING):
    kwargs = {}
    if default is not MISSING:
        kwargs['default'] = default
    if default_factory is not MISSING:
        kwargs['default_factory'] = default_factory
    return dc_field(**kwargs)


class _BaseModelMeta(type):
    def __new__(mcls, name, bases, ns):
        cls = super().__new__(mcls, name, bases, ns)
        if name != 'BaseModel':
            cls = dataclass(cls)
        return cls


class BaseModel(metaclass=_BaseModelMeta):
    @classmethod
    def model_validate(cls, data: dict[str, Any]):
        return cls(**data)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump_json(self, ensure_ascii: bool = True) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=ensure_ascii)
