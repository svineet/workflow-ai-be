from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class MathAddInput(BaseModel):
    a: float = Field(..., description="First addend")
    b: float = Field(..., description="Second addend")


class MathAddOutput(BaseModel):
    result: float = Field(..., description="Sum of a and b")


@register("math.add")
class MathAddBlock(Block):
    type_name = "math.add"
    summary = "Add two numbers"
    input_model = MathAddInput
    output_model = MathAddOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        a = float(self.params.get("a", 0))
        b = float(self.params.get("b", 0))
        return MathAddOutput(result=a + b).model_dump() 