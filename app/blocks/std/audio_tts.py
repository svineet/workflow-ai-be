from __future__ import annotations

import base64
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext
from ...server.settings import settings
from .media import Media


class AudioTTSSettings(BaseModel):
    text: str
    model: str = Field(default="tts-1")
    voice: str = Field(default="alloy")
    format: Literal["mp3", "wav"] = Field(default="mp3")
    timeout_seconds: int = Field(default=60)


class AudioTTSOutput(BaseModel):
    media: Media


@register("audio.tts")
class AudioTTSBlock(Block):
    type_name = "audio.tts"
    summary = "Text to speech via OpenAI TTS"
    settings_model = AudioTTSSettings
    output_model = AudioTTSOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        upstream = input.get("upstream") or {}
        extra_ctx = {"settings": s, "trigger": input.get("trigger") or {}, "nodes": upstream}
        try:
            text = self.render_expression(str(s.get("text") or ""), upstream=upstream, extra=extra_ctx)
        except Exception:
            text = str(s.get("text") or "")
        if not text:
            raise ValueError("audio.tts requires non-empty 'text'")

        data_bytes: bytes
        mime = "audio/mpeg" if s.get("format") == "mp3" else "audio/wav"
        filename = f"speech.{s.get('format')}"

        if not settings.OPENAI_API_KEY:
            # 1-second silence in mp3 header min (very small mock)
            data_bytes = b"\x49\x44\x33"  # minimal header-like stub, not a real mp3
        else:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                resp = await client.audio.speech.create(
                    model=s.get("model") or "tts-1",
                    voice=s.get("voice") or "alloy",
                    input=text,
                    response_format=s.get("format") or "mp3",
                )
                # openai v1 returns bytes-like in resp
                # Some SDKs return .content or .data; attempt common accessors
                data_bytes = getattr(resp, "content", None) or getattr(resp, "data", None) or bytes(resp)
                if isinstance(data_bytes, str):
                    data_bytes = data_bytes.encode("utf-8")
                if not isinstance(data_bytes, (bytes, bytearray)):
                    data_bytes = bytes(data_bytes)
                await client.close()

                # Play the audio as well, just for testing (docker: try mpg123 or aplay if available)
                try:
                    import io
                    import subprocess
                    import tempfile
                    import os

                    # Write to a temp file and play with mpg123 (for mp3) or aplay (for wav) if available
                    fmt = s.get("format") or "mp3"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}") as tmpf:
                        tmpf.write(data_bytes)
                        tmpf.flush()
                        tmpf_name = tmpf.name
                    try:
                        played = False
                        if fmt == "mp3":
                            # Try mpg123
                            if subprocess.call(["which", "mpg123"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                                subprocess.call(["mpg123", tmpf_name])
                                played = True
                        if not played and fmt in ("wav", "wave"):
                            # Try aplay
                            if subprocess.call(["which", "aplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                                subprocess.call(["aplay", tmpf_name])
                                played = True
                        if not played:
                            await ctx.logger("audio.tts: No audio player found in docker (mpg123/aplay missing)", {})
                    finally:
                        os.unlink(tmpf_name)
                except Exception as play_ex:
                    await ctx.logger(f"audio.tts: failed to play audio locally in docker: {play_ex}", {"error": str(play_ex)})


            except Exception as ex:
                await ctx.logger(f"audio.tts: openai error, using silent fallback: {ex}", {"error": str(ex)})
                data_bytes = b"\x49\x44\x33"

        b64 = base64.b64encode(data_bytes).decode("ascii")
        media = Media(kind="audio", mime=mime, bytes_b64=b64, filename=filename, size=len(data_bytes))
        return AudioTTSOutput(media=media).model_dump() 