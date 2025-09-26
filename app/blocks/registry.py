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
        settings_schema_fn = getattr(cls, "settings_schema", None)
        output_schema_fn = getattr(cls, "output_schema", None)

        settings_schema = settings_schema_fn() if callable(settings_schema_fn) else None
        output_schema = output_schema_fn() if callable(output_schema_fn) else None

        # Derive required vs optional fields from Pydantic model when available
        required_fields: list[str] = []
        advanced_fields: list[str] = []
        try:
            Model = getattr(cls, "settings_model", None)
            if Model is not None:
                for name, field in Model.model_fields.items():  # type: ignore[attr-defined]
                    if field.is_required():  # type: ignore[attr-defined]
                        required_fields.append(name)
                    else:
                        advanced_fields.append(name)
        except Exception:
            pass

        specs.append({
            "type": t,
            "kind": "executor",
            "summary": getattr(cls, "summary", ""),
            "settings_schema": settings_schema,
            "output_schema": output_schema,
            "required_fields": required_fields if required_fields else None,
            "advanced_fields": advanced_fields if advanced_fields else None,
        })
    return specs


def get_block_class(type_name: str) -> Type[Block] | None:
    return _CLASS_REGISTRY.get(type_name)
