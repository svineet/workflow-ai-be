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
    if not isinstance(input, dict):  # debug guard
        print("run_block received non-dict input:", type(input))
    settings = (input or {}).get("settings") or {}
    instance = cls(settings=settings)
    return instance.run(input, ctx)


def list_blocks() -> Mapping[str, Block]:
    return {key: (lambda *_args, **_kwargs: None) for key in sorted(_CLASS_REGISTRY.keys())}


def list_block_specs() -> list[Dict[str, Any]]:
    specs: list[Dict[str, Any]] = []
    for t, cls in sorted(_CLASS_REGISTRY.items(), key=lambda kv: kv[0]):
        settings_schema = getattr(cls, "settings_schema", None)
        output_schema = getattr(cls, "output_schema", None)
        specs.append({
            "type": t,
            "kind": getattr(cls, "kind", "executor"),
            "summary": getattr(cls, "summary", ""),
            "settings_schema": settings_schema() if callable(settings_schema) else None,
            "output_schema": output_schema() if callable(output_schema) else None,
            "extras": cls.extras() if hasattr(cls, "extras") and callable(getattr(cls, "extras")) else None,
        })
    return specs


def get_block_class(type_name: str) -> Type[Block] | None:
    return _CLASS_REGISTRY.get(type_name)
