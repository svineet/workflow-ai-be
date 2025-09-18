from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from openai import AsyncOpenAI

from ..registry import register
from ..base import Block, RunContext
from ...server.settings import settings


class LlmSimpleInput(BaseModel):
    prompt: str = Field(..., description="Prompt text to send to LLM")
    model: Optional[str] = Field(default="gpt-4o-mini", description="OpenAI model")


class LlmSimpleOutput(BaseModel):
    text: str


@register("llm.simple")
class LlmSimpleBlock(Block):
    type_name = "llm.simple"
    summary = "Generate text using OpenAI; falls back to uppercase when no API key"
    input_model = LlmSimpleInput
    output_model = LlmSimpleOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        prompt = self.params.get("prompt")
        model = self.params.get("model") or "gpt-4o-mini"
        if not prompt:
            raise ValueError("llm.simple requires 'prompt'")

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
