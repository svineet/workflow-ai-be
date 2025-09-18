from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class TemplateInput(BaseModel):
    template: str = Field(..., description="Jinja-like template string with {{placeholders}}")
    values: Dict[str, Any] = Field(default_factory=dict, description="Values to substitute into template")


class TemplateOutput(BaseModel):
    text: str


@register("transform.template")
class TemplateBlock(Block):
    type_name = "transform.template"
    summary = "Render a simple template by replacing {{keys}} with values"
    input_model = TemplateInput
    output_model = TemplateOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = str(self.params.get("template", ""))
        values = dict(self.params.get("values") or {})
        # naive replacement: {{key}} -> str(value)
        out = s
        for k, v in values.items():
            out = out.replace(f"{{{{{k}}}}}", str(v))
        return TemplateOutput(text=out).model_dump() 