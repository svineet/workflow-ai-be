from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class StartInput(BaseModel):
    payload: Optional[Dict[str, Any]] = Field(None, description="Explicit payload to emit; if not set, uses trigger payload")


class StartOutput(BaseModel):
    data: Any


@register("start")
class StartBlock(Block):
    type_name = "start"
    summary = "Start node returns provided payload or trigger payload"
    input_model = StartInput
    output_model = StartOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        payload = self.params.get("payload")
        if payload is None:
            payload = (input.get("trigger") or {})
        return StartOutput(data=payload).model_dump()
