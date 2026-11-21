"""把领域对象转成可 JSON 化的普通结构。"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum


def 转普通值(obj):
    if is_dataclass(obj):
        return {k: 转普通值(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: 转普通值(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [转普通值(v) for v in obj]
    return obj
