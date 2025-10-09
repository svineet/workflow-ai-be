from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class UIAudioSettings(BaseModel):
    file: Any
    title: Optional[str] = Field(default=None)


class UIAudioOutput(BaseModel):
    ok: bool
    file: Any
    title: Optional[str] = None


@register("ui.audio")
class UIAudioBlock(Block):
    type_name = "ui.audio"
    summary = "UI audio sink (frontend renders <audio>)"
    settings_model = UIAudioSettings
    output_model = UIAudioOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        upstream = input.get("upstream") or {}
        extra_ctx = {"settings": s, "trigger": input.get("trigger") or {}, "nodes": upstream}
        file_value = s.get("file")
        if isinstance(file_value, str):
            try:
                file_value = self.render_expression(file_value, upstream=upstream, extra=extra_ctx)
            except Exception:
                pass
        return UIAudioOutput(ok=True, file=file_value, title=s.get("title")).model_dump() 