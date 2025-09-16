from __future__ import annotations

from typing import Any, Dict

from openai import AsyncOpenAI

from ..registry import register
from ..base import RunContext
from ...server.settings import settings


@register("llm.simple")
async def llm_simple_block(input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
    params: Dict[str, Any] = input.get("params") or {}
    prompt = params.get("prompt")
    model = params.get("model") or "gpt-4o-mini"
    if not prompt:
        raise ValueError("llm.simple requires 'prompt'")

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return {"text": str(prompt).upper()}

    client = AsyncOpenAI(api_key=api_key)
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = completion.choices[0].message.content or ""
        return {"text": text}
    finally:
        await client.close()
