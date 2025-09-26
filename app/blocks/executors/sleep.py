from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class SleepSettings(BaseModel):
    seconds: Optional[float] = Field(0.1, ge=0, description="Seconds to sleep (non-blocking)")
    jitter_ms: Optional[int] = Field(0, ge=0, description="Optional jitter (milliseconds) added to seconds")


class SleepOutput(BaseModel):
    slept: float


@register("util.sleep")
class SleepBlock(Block):
    type_name = "util.sleep"
    summary = "Asynchronously sleep for N seconds"
    settings_model = SleepSettings
    output_model = SleepOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        secs = float(self.settings.get("seconds", 0.1))
        jitter_ms = int(self.settings.get("jitter_ms", 0))
        total = secs + max(0, jitter_ms) / 1000.0
        await asyncio.sleep(total)
        return SleepOutput(slept=total).model_dump() 