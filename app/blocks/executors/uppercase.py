from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class UppercaseSettings(BaseModel):
    text: str = Field(..., description="Text to transform to uppercase")
    trim_whitespace: bool = Field(default=False, description="Trim leading/trailing whitespace before converting")


class UppercaseOutput(BaseModel):
    text: str = Field(..., description="Uppercased text result")


@register("transform.uppercase")
class UppercaseBlock(Block):
    type_name = "transform.uppercase"
    summary = "Convert a text string to uppercase"
    settings_model = UppercaseSettings
    output_model = UppercaseOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        raw = str(self.settings.get("text", ""))
        # Render expressions if present
        value = self.render_expression(raw, upstream=input.get("upstream") or {}, extra={"settings": self.settings, "trigger": input.get("trigger") or {}})
        if self.settings.get("trim_whitespace"):
            value = str(value).strip()
        return UppercaseOutput(text=str(value).upper()).model_dump() 