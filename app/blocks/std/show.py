from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class ShowSettings(BaseModel):
    title: Optional[str] = Field(default=None, description="Optional title to display in UI")


class ShowOutput(BaseModel):
    data: Any


@register("show")
class ShowBlock(Block):
    type_name = "show"
    summary = "Display input data in the UI; terminal sink block"
    settings_model = ShowSettings
    output_model = ShowOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        upstream = input.get("upstream") or {}
        payload = {"upstream": upstream, "settings": self.settings, "title": self.settings.get("title")}
        await ctx.logger("ShowBlock input", {"payload": payload})
        return ShowOutput(data=payload).model_dump() 