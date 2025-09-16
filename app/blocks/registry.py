from __future__ import annotations

from typing import Any, Callable, Dict, Mapping

from .base import Block

_REGISTRY: Dict[str, Block] = {}


def register(type_name: str) -> Callable[[Block], Block]:
    def decorator(func: Block) -> Block:
        _REGISTRY[type_name] = func
        return func
    return decorator


def run_block(type_name: str, input: Dict[str, Any], ctx) -> Any:
    block = _REGISTRY.get(type_name)
    if block is None:
        raise ValueError(f"Unknown block type: {type_name}")
    return block(input, ctx)


def list_blocks() -> Mapping[str, Block]:
    return dict(_REGISTRY)
