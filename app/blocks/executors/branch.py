from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class BranchInput(BaseModel):
    condition: bool = Field(..., description="Boolean condition to include in output")


class BranchOutput(BaseModel):
    condition: bool


@register("control.branch")
class BranchBlock(Block):
    type_name = "control.branch"
    summary = "Output the given boolean condition (routing TBD in engine)"
    input_model = BranchInput
    output_model = BranchOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        cond = bool(self.params.get("condition", False))
        return BranchOutput(condition=cond).model_dump() 