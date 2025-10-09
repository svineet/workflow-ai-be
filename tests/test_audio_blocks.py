from __future__ import annotations

import base64
import asyncio
import pytest

from app.blocks.std.audio_tts import AudioTTSBlock
from app.blocks.std.audio_stt import AudioSTTBlock
from app.blocks.std.ui_audio import UIAudioBlock
from app.blocks.base import RunContext
from app.services.gcs import GCSWriter
from app.services.http import create_http_client


def test_ui_audio_echo():
    http = create_http_client()
    ctx = RunContext(gcs=GCSWriter(), http=http, logger=lambda m, d=None, node_id=None: asyncio.sleep(0))
    blk = UIAudioBlock({"file": {"web_url": "https://example.com/audio.mp3"}, "title": "Sample"})
    out = asyncio.get_event_loop().run_until_complete(blk.run({"upstream": {}, "trigger": {}}, ctx))
    assert out["ok"] is True
    assert out["file"]["web_url"].startswith("https://example.com/")


def test_audio_tts_fallback_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    http = create_http_client()
    ctx = RunContext(gcs=GCSWriter(), http=http, logger=lambda m, d=None, node_id=None: asyncio.sleep(0))
    blk = AudioTTSBlock({"text": "Hello world"})
    out = asyncio.get_event_loop().run_until_complete(blk.run({"upstream": {}, "trigger": {}}, ctx))
    media = out["media"]
    assert media["kind"] == "audio"
    assert media["bytes_b64"]


def test_audio_stt_with_bytes(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    http = create_http_client()
    ctx = RunContext(gcs=GCSWriter(), http=http, logger=lambda m, d=None, node_id=None: asyncio.sleep(0))
    fake_bytes = b"\x49\x44\x33"
    media = {
        "kind": "audio",
        "mime": "audio/mpeg",
        "bytes_b64": base64.b64encode(fake_bytes).decode("ascii"),
    }
    blk = AudioSTTBlock({"media": media})
    out = asyncio.get_event_loop().run_until_complete(blk.run({"upstream": {}, "trigger": {}}, ctx))
    assert "text" in out 