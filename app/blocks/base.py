from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Type

import httpx
from pydantic import BaseModel

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
    Optionally set `input_model` and `output_model` (Pydantic) to expose schemas.
    """

    type_name: str = ""
    summary: str = ""
    input_model: Optional[Type[BaseModel]] = None
    output_model: Optional[Type[BaseModel]] = None

    def __init__(self, params: Dict[str, Any] | None = None) -> None:
        self.params: Dict[str, Any] = self.validate_params(params or {})

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        Model = self.input_model
        if Model is not None:
            model = Model.model_validate(params)  # type: ignore[arg-type]
            return model.model_dump()
        return params

    @classmethod
    def input_schema(cls) -> Optional[Dict[str, Any]]:
        if cls.input_model is None:
            return None
        return cls.input_model.model_json_schema()  # type: ignore[return-value]

    @classmethod
    def output_schema(cls) -> Optional[Dict[str, Any]]:
        if cls.output_model is None:
            return None
        return cls.output_model.model_json_schema()  # type: ignore[return-value]

    async def before(self, input: Dict[str, Any], ctx: RunContext) -> None:  # noqa: ARG002
        return None

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:  # pragma: no cover - to be implemented by subclasses
        raise NotImplementedError

    async def after(self, input: Dict[str, Any], output: Dict[str, Any], ctx: RunContext) -> None:  # noqa: ARG002
        return None
