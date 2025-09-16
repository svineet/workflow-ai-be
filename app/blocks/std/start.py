from __future__ import annotations

from typing import Any, Dict

from ..registry import register
from ..base import RunContext


@register("start")
async def start_block(input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
    params = input.get("params") or {}
    payload = params.get("payload")
    if payload is None:
        trigger = input.get("trigger") or {}
        payload = trigger
    return {"data": payload}
