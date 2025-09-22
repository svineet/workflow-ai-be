from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class ShowSettings(BaseModel):
    template: Optional[str] = Field(default=None, description="Jinja template to render as Markdown in UI")


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
        template = (self.settings or {}).get("template") or ""
        node_id = input.get("node_id")
        # Render the template using Jinja with upstream + extra context
        extra_ctx = {
            "settings": self.settings or {},
            "trigger": input.get("trigger_payload") or input.get("trigger") or {},
            "upstream": upstream,
        }
        try:
            rendered = self.render_expression(template, upstream=upstream, extra=extra_ctx)
        except Exception:
            rendered = ""
        payload = {"upstream": upstream, "settings": self.settings, "template": template, "rendered": rendered}
        # Build concise inline summary for message
        upstream_keys = list((upstream or {}).keys())[:20]
        # Try to extract a short preview from first upstream value
        preview_val = None
        try:
            if upstream_keys:
                first = upstream.get(upstream_keys[0])
                if isinstance(first, dict):
                    if "text" in first:
                        preview_val = str(first.get("text"))[:120]
                    else:
                        preview_val = str(first)[:120]
                else:
                    preview_val = str(first)[:120]
        except Exception:
            preview_val = None

        message = f"ShowBlock rendered upstream_keys={upstream_keys}"
        if preview_val:
            message += f" preview={preview_val!r}"

        # Log a compact preview and full payload in data
        try:
            preview = {"upstream_keys": upstream_keys, "preview": preview_val, "has_rendered": bool(rendered)}
        except Exception:
            preview = {"upstream_keys": "<error>"}
        await ctx.logger(message, {"preview": preview, "full": payload}, node_id=node_id)
        return ShowOutput(data=payload).model_dump() 