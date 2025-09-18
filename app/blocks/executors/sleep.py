from __future__ import annotations

import asyncio
from typing import Any, Dict

from pydantic import BaseModel, Field, condecimal

from ..registry import register
from ..base import Block, RunContext


class SleepInput(BaseModel):
    seconds: float = Field(0.1, ge=0, description="Seconds to sleep (non-blocking)")


class SleepOutput(BaseModel):
    slept: float


@register("util.sleep")
class SleepBlock(Block):
    type_name = "util.sleep"
    summary = "Asynchronously sleep for N seconds"
    input_model = SleepInput
    output_model = SleepOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        secs = float(self.params.get("seconds", 0))
        await asyncio.sleep(secs)
        return SleepOutput(slept=secs).model_dump() 