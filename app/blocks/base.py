from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Type

import httpx
from pydantic import BaseModel
import re
from jinja2 import Environment, StrictUndefined

from ..services.gcs import GCSWriter


@dataclass
class RunContext:
    gcs: GCSWriter
    http: httpx.AsyncClient
    logger: Callable[[str, Dict[str, Any] | None, str | None], Awaitable[None]]


class Block:
    """Unified class-based block with schema support.

    Subclasses should set `type_name` and implement `run`.
    They may override `before` and `after` for lifecycle hooks.
    Define a single `settings_model` for design-time configuration.
    """

    type_name: str = ""
    summary: str = ""
    settings_model: Optional[Type[BaseModel]] = None
    output_model: Optional[Type[BaseModel]] = None

    def __init__(self, settings: Dict[str, Any] | None = None) -> None:
        self.settings: Dict[str, Any] = self.validate_settings(settings or {})

    def validate_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        Model = self.settings_model
        if Model is not None:
            model = Model.model_validate(settings)  # type: ignore[arg-type]
            return model.model_dump()
        return settings

    @classmethod
    def settings_schema(cls) -> Optional[Dict[str, Any]]:
        if cls.settings_model is None:
            return None
        return cls.settings_model.model_json_schema()  # type: ignore[return-value]

    @classmethod
    def output_schema(cls) -> Optional[Dict[str, Any]]:
        if cls.output_model is None:
            return None
        return cls.output_model.model_json_schema()  # type: ignore[return-value]

    def render_expression(self, template: str, *, upstream: Dict[str, Any] | None = None, extra: Dict[str, Any] | None = None) -> str:
        """Render with Jinja2 using context composed of upstream + extra (settings/trigger/etc)."""
        if not isinstance(template, str):
            return str(template)
        ctx: Dict[str, Any] = {}
        if upstream:
            ctx.update(upstream)
        if extra:
            ctx.update(extra)
        env = Environment(undefined=StrictUndefined, autoescape=False)
        try:
            return env.from_string(template).render(**ctx)
        except Exception:
            # On undefined variables or errors, fall back to empty-string behavior
            # by replacing missing variables with "" using a permissive env.
            env2 = Environment(autoescape=False)
            return env2.from_string(template).render(**ctx)

    async def before(self, input: Dict[str, Any], ctx: RunContext) -> None:  # noqa: ARG002
        return None

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:  # pragma: no cover - to be implemented by subclasses
        raise NotImplementedError

    async def after(self, input: Dict[str, Any], output: Dict[str, Any], ctx: RunContext) -> None:  # noqa: ARG002
        return None
