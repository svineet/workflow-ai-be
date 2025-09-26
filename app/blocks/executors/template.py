from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class TemplateSettings(BaseModel):
    template: str = Field(..., description="Jinja-like template string with {{placeholders}}")
    values: Dict[str, Any] = Field(default_factory=dict, description="Values to substitute into template")


class TemplateOutput(BaseModel):
    text: str


@register("transform.template")
class TemplateBlock(Block):
    type_name = "transform.template"
    summary = "Render a simple template by replacing {{keys}} with values"
    settings_model = TemplateSettings
    output_model = TemplateOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        s_str = str(s.get("template", ""))
        upstream = input.get("upstream") or {}
        # Expose upstream node ids directly to their data payloads, e.g., {{ s.name }}
        flat_nodes_ctx: Dict[str, Any] = {}
        try:
            for k, v in (upstream or {}).items():
                if isinstance(v, dict) and "data" in v:
                    flat_nodes_ctx[k] = v.get("data")
                else:
                    flat_nodes_ctx[k] = v
        except Exception:
            flat_nodes_ctx = {}
        extra = {"settings": s, **(s.get("values") or {}), **flat_nodes_ctx}
        out = self.render_expression(s_str, upstream=upstream, extra=extra)
        return TemplateOutput(text=out).model_dump() 