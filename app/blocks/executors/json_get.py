from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class JsonGetSettings(BaseModel):
    path: List[str] = Field(..., description="Path keys to traverse into")
    source: Dict[str, Any] = Field(default_factory=dict, description="Source JSON to traverse; if omitted, will use upstream/start data when implemented")


class JsonGetOutput(BaseModel):
    value: Any = Field(None, description="Extracted value or null if missing")


@register("json.get")
class JsonGetBlock(Block):
    type_name = "json.get"
    summary = "Extract a nested value from JSON by path"
    settings_model = JsonGetSettings
    output_model = JsonGetOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        src = dict(self.settings.get("source") or {})
        path = list(self.settings.get("path") or [])
        cur: Any = src
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                cur = None
                break
        return JsonGetOutput(value=cur).model_dump() 