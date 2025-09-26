from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class StartSettings(BaseModel):
    payload: Optional[Dict[str, Any]] = Field(None, description="Explicit payload to emit; if not set, uses trigger payload")


@register("start")
class StartBlock(Block):
    type_name = "start"
    summary = "Start node returns provided payload or trigger payload (as raw object)"
    settings_model = StartSettings
    output_model = None  # arbitrary shape

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        payload = self.settings.get("payload")
        if payload is None:
            payload = (input.get("trigger") or {})
        # Ensure we return an object so downstream can reference {{ nodeId.key }}
        if isinstance(payload, dict):
            return payload
        return {"value": payload}
