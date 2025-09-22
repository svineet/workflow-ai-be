from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from openai import AsyncOpenAI

from ..registry import register
from ..base import Block, RunContext
from ...server.settings import settings


class LlmSimpleSettings(BaseModel):
    prompt: str = Field(..., description="Prompt text to send to LLM (supports {{ }} substitutions)")
    model: Optional[str] = Field(default="gpt-4o-mini", description="OpenAI model")


class LlmSimpleOutput(BaseModel):
    text: str


@register("llm.simple")
class LlmSimpleBlock(Block):
    type_name = "llm.simple"
    summary = "Generate text using OpenAI; falls back to uppercase when no API key"
    settings_model = LlmSimpleSettings
    output_model = LlmSimpleOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        raw_prompt = s.get("prompt")
        model = s.get("model") or "gpt-4o-mini"
        if not raw_prompt:
            raise ValueError("llm.simple requires 'prompt'")

        extra_ctx = {"settings": s, "trigger": input.get("trigger") or {}}
        prompt = self.render_expression(str(raw_prompt), upstream=input.get("upstream") or {}, extra=extra_ctx)

        node_id = input.get("node_id")
        # Log request preview
        await ctx.logger(
            f"llm.simple: sending [{model}]",
            {"model": model, "prompt_preview": str(prompt)[:500]},
            node_id=node_id,
        )

        api_key = settings.OPENAI_API_KEY
        if not api_key:
            text = str(prompt).upper()
            await ctx.logger(
                f"llm.simple: fallback [{model}]",
                {"reason": "no_api_key", "text_preview": text[:500]},
                node_id=node_id,
            )
            return LlmSimpleOutput(text=text).model_dump()

        client = AsyncOpenAI(api_key=api_key)
        try:
            completion = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=1.0,
            )
            text = completion.choices[0].message.content or ""
            await ctx.logger(
                f"llm.simple: received [{model}]",
                {"model": model, "text_preview": text[:1000]},
                node_id=node_id,
            )
            return LlmSimpleOutput(text=text).model_dump()
        finally:
            await client.close()
