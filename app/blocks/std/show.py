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
        node_id = input.get("node_id")
        # Build concise inline summary for message
        title = payload.get("title")
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

        message = f"ShowBlock input title={title!r} upstream_keys={upstream_keys}"
        if preview_val:
            message += f" preview={preview_val!r}"

        # Log a compact preview and full payload in data
        try:
            preview = {"title": title, "upstream_keys": upstream_keys, "preview": preview_val}
        except Exception:
            preview = {"title": title, "upstream_keys": "<error>"}
        await ctx.logger(message, {"preview": preview, "full": payload}, node_id=node_id)
        return ShowOutput(data=payload).model_dump() 