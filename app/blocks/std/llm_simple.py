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

        api_key = settings.OPENAI_API_KEY
        if not api_key:
            return LlmSimpleOutput(text=str(prompt).upper()).model_dump()

        client = AsyncOpenAI(api_key=api_key)
        try:
            completion = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            text = completion.choices[0].message.content or ""
            return LlmSimpleOutput(text=text).model_dump()
        finally:
            await client.close()
