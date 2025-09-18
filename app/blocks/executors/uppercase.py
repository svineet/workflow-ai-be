from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class UppercaseInput(BaseModel):
    text: str = Field(..., description="Text to transform to uppercase")


class UppercaseOutput(BaseModel):
    text: str = Field(..., description="Uppercased text result")


@register("transform.uppercase")
class UppercaseBlock(Block):
    type_name = "transform.uppercase"
    summary = "Convert a text string to uppercase"
    input_model = UppercaseInput
    output_model = UppercaseOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        value = self.params.get("text", "")
        return UppercaseOutput(text=str(value).upper()).model_dump() 