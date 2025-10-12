from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class WebSearchToolSettings(BaseModel):
    name: Optional[str] = Field(default=None, description="Optional tool name override")


class WebSearchToolOutput(BaseModel):
    ok: bool


@register("tool.websearch")
class WebSearchToolBlock(Block):
    type_name = "tool.websearch"
    summary = "Web search tool (Agents SDK hosted tool)"
    settings_model = WebSearchToolSettings
    output_model = WebSearchToolOutput
    tool_compatible = True

    @classmethod
    def extras(cls) -> Dict[str, Any]:
        return {"toolCompatible": True}

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        return WebSearchToolOutput(ok=True).model_dump()


