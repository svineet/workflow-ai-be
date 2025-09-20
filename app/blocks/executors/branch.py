from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class BranchSettings(BaseModel):
    expression: str = Field(..., description="Jinja expression; resolves using upstream/settings/trigger context")


class BranchOutput(BaseModel):
    condition: bool


@register("control.branch")
class BranchBlock(Block):
    type_name = "control.branch"
    summary = "Evaluate an expression against context and output a boolean"
    settings_model = BranchSettings
    output_model = BranchOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        expr = self.settings.get("expression")
        if not expr:
            raise ValueError("control.branch requires 'expression'")

        extra = {
            "settings": self.settings,
            "trigger": input.get("trigger") or {},
        }
        upstream = input.get("upstream") or {}
        rendered = self.render_expression(str(expr), upstream=upstream, extra=extra)
        cond = bool(str(rendered).strip())
        return BranchOutput(condition=cond).model_dump() 