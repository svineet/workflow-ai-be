from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class HTTPToolSettings(BaseModel):
    name: Optional[str] = Field(default=None, description="Optional tool name override")


class HTTPToolOutput(BaseModel):
    ok: bool


@register("tool.http_request")
class HTTPRequestToolBlock(Block):
    type_name = "tool.http_request"
    summary = "HTTP request tool (Agents SDK function tool wrapper)"
    settings_model = HTTPToolSettings
    output_model = HTTPToolOutput
    tool_compatible = True

    @classmethod
    def extras(cls) -> Dict[str, Any]:
        return {"toolCompatible": True}

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        # Tool nodes are not executed directly by the engine; they are invoked by the agent
        return HTTPToolOutput(ok=True).model_dump()


