from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Type

from .base import Block

_CLASS_REGISTRY: Dict[str, Type[Block]] = {}


def register(type_name: str) -> Callable[[Type[Block]], Type[Block]]:
    def decorator(cls: Type[Block]) -> Type[Block]:
        _CLASS_REGISTRY[type_name] = cls
        return cls
    return decorator


def run_block(type_name: str, input: Dict[str, Any], ctx) -> Any:
    cls = _CLASS_REGISTRY.get(type_name)
    if cls is None:
        raise ValueError(f"Unknown block type: {type_name}")
    params = (input or {}).get("params") or {}
    instance = cls(params=params)
    return instance.run(input, ctx)


def list_blocks() -> Mapping[str, Block]:
    return {key: (lambda *_args, **_kwargs: None) for key in sorted(_CLASS_REGISTRY.keys())}


def list_block_specs() -> list[Dict[str, Any]]:
    specs: list[Dict[str, Any]] = []
    for t, cls in sorted(_CLASS_REGISTRY.items(), key=lambda kv: kv[0]):
        specs.append({
            "type": t,
            "kind": "executor",  # unified class-based blocks; keep value for FE compatibility
            "summary": getattr(cls, "summary", ""),
            "input_schema": cls.input_schema(),
            "output_schema": cls.output_schema(),
        })
    return specs
