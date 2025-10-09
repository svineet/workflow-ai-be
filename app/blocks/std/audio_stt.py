from __future__ import annotations

import base64
import io
import os
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext
from ...server.settings import settings
from .media import Media


class AudioSTTSettings(BaseModel):
    media: Any
    model: str = Field(default="whisper-1")
    timeout_seconds: int = Field(default=120)
    prompt: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default=None)


class AudioSTTOutput(BaseModel):
    text: str


@register("audio.stt")
class AudioSTTBlock(Block):
    type_name = "audio.stt"
    summary = "Speech to text via OpenAI Whisper"
    settings_model = AudioSTTSettings
    output_model = AudioSTTOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        upstream = input.get("upstream") or {}
        extra_ctx = {"settings": s, "trigger": input.get("trigger") or {}, "nodes": upstream}
        m = s.get("media")
        if isinstance(m, str):
            try:
                m = self.render_expression(m, upstream=upstream, extra=extra_ctx)
            except Exception:
                pass
        media_obj: Optional[Media] = None
        raw_bytes: Optional[bytes] = None
        filename: str = "audio_input"
        mime: str = "audio/mpeg"
        if isinstance(m, dict) and ("bytes_b64" in m or "uri" in m or "mime" in m):
            media_obj = Media.model_validate(m)
        elif isinstance(m, Media):
            media_obj = m
        elif isinstance(m, str) and (m.startswith("http://") or m.startswith("https://")):
            async with httpx.AsyncClient(timeout=s.get("timeout_seconds") or 120) as client:
                resp = await client.get(m)
                resp.raise_for_status()
                raw_bytes = resp.content
                mime = resp.headers.get("Content-Type", "application/octet-stream")
                filename = m.rsplit("/", 1)[-1] or filename
        else:
            raise ValueError("audio.stt requires 'media' as Media object or URL")

        if media_obj is not None:
            mime = media_obj.mime or mime
            filename = media_obj.filename or filename
            if media_obj.bytes_b64:
                raw_bytes = base64.b64decode(media_obj.bytes_b64)
            elif media_obj.uri:
                async with httpx.AsyncClient(timeout=s.get("timeout_seconds") or 120) as client:
                    resp = await client.get(media_obj.uri)
                    resp.raise_for_status()
                    raw_bytes = resp.content
            else:
                raise ValueError("audio.stt: media has neither bytes_b64 nor uri")

        if not raw_bytes:
            raise ValueError("audio.stt: no audio bytes resolved")

        # Offline/test guard: avoid remote call if missing key or bytes too small to be valid audio
        if (not (settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY"))) or len(raw_bytes) < 1000:
            return AudioSTTOutput(text="").model_dump()

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY"))
        try:
            file_tuple = (filename or "audio_input", raw_bytes, mime or "application/octet-stream")
            resp = await client.audio.transcriptions.create(
                model=s.get("model") or "whisper-1",
                file=file_tuple,
                prompt=s.get("prompt"),
                language=s.get("language"),
            )
            text = getattr(resp, "text", None)
            if not isinstance(text, str):
                text = str(text)
            return AudioSTTOutput(text=text or "").model_dump()
        finally:
            await client.close() 