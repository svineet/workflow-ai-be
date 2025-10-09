import asyncio
import json
import os
import sys
from typing import Any, Dict

# Ensure 'app' is importable when running as a script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base, Workflow, Run, NodeRun, Log
from app.db.session import engine, SessionFactory


WEATHER_GRAPH: Dict[str, Any] = {
    "nodes": [
        {
            "id": "n1",
            "type": "http.request",
            "settings": {
                "method": "GET",
                "url": "https://api.github.com/repos/python/cpython",
                "headers": {"Accept": "application/vnd.github+json"},
                "follow_redirects": True,
                "timeout_seconds": 15.0,
            },
        },
        {
            "id": "n2",
            "type": "llm.simple",
            "settings": {
                "prompt": "Summarize this repository data: {{ n1.data }}",
                "model": "gpt-4o-mini",
            },
        },
        {
            "id": "n3",
            "type": "show",
            "settings": {"template": "LLM Summary"},
        },
    ],
    "edges": [
        {"id": "e1", "from": "n1", "to": "n2"},
        {"id": "e2", "from": "n2", "to": "n3"},
    ],
}


MINIMAL_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "s", "type": "start", "settings": {"payload": {"hello": "world"}}},
        {"id": "show", "type": "show", "settings": {"template": "Hello"}},
    ],
    "edges": [
        {"id": "e1", "from": "s", "to": "show"},
    ],
}


SLEEP_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "sleep1", "type": "util.sleep", "settings": {"seconds": 0.2}},
        {"id": "sleep2", "type": "util.sleep", "settings": {"seconds": 0.2}},
        {"id": "sleep3", "type": "util.sleep", "settings": {"seconds": 0.2}},
    ],
    "edges": [
        {"id": "e1", "from": "sleep1", "to": "sleep2"},
        {"id": "e2", "from": "sleep2", "to": "sleep3"},
    ],
}


AGENT_CALC_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start", "settings": {"payload": {"query": "(12 + 7) * 3"}}},
        {
            "id": "agent",
            "type": "agent.react",
            "settings": {
                "system": "You are a math assistant. Use the calculator tool to compute the result of the user's query.",
                "prompt": "Please compute this: {{ start.query }}",
                "model": "gpt-5",
                "temperature": 1,
                "max_steps": 4
            },
        },
        {"id": "calc", "type": "tool.calculator", "settings": {}},
        {"id": "show", "type": "show", "settings": {"template": "Agent final: {{ upstream.agent.final }}"}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "agent"},
        {"id": "e2", "from": "agent", "to": "show"},
        {"id": "t1", "from": "agent", "to": "calc", "kind": "tool"},
    ],
}


COMPOSIO_GMAIL_EMAIL_GRAPH: Dict[str, Any] = {
    "nodes": [
        {
            "id": "agent",
            "type": "agent.react",
            "settings": {
                "system": "You are a helpful assistant, with tools. ",
                "prompt": "Write a short funny one‑liner about coding in Python. Send it to saivineet89@gmail.com.\n Don't ask. Just frame and send. Also what tools do you have access to?",
                "tools": [],
                "model": "gpt-5",
                "temperature": 1,
                "max_steps": 3,
                "timeout_seconds": 60
            },
        },
        {
            "id": "email",
            "type": "tool.composio",
            "settings": {
                "toolkit": "GMAIL",
                "tool_slug": "GMAIL_SEND_EMAIL",
                "args": {
                    "to": ["saivineet89+agent@gmail.com"],
                    "subject": "A joke for you",
                    "body": "{{ upstream.agent.final }}"
                }
            },
        },
    ],
    "edges": [
        # Tool linkage from agent to tool node
        {"id": "t1", "from": "agent", "to": "email", "kind": "tool"}
    ],
}


AUDIO_TTS_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "s", "type": "start", "settings": {"payload": {"text": "Hello from Workflow AI"}}},
        {"id": "tts", "type": "audio.tts", "settings": {"text": "{{ s.text }}", "voice": "alloy", "format": "mp3"}},
        {"id": "play", "type": "ui.audio", "settings": {"file": "{{ tts.media }}", "title": "TTS Output"}},
    ],
    "edges": [
        {"id": "e1", "from": "s", "to": "tts"},
        {"id": "e2", "from": "tts", "to": "play"},
    ],
}


AUDIO_STT_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "s", "type": "start", "settings": {"payload": {"url": "https://file-examples.com/storage/fe9f4e6f0c7e1/audio.mp3"}}},
        {"id": "stt", "type": "audio.stt", "settings": {"media": "{{ s.url }}"}},
        {"id": "show", "type": "show", "settings": {"template": "Transcribed: {{ upstream.stt.text }}"}},
    ],
    "edges": [
        {"id": "e1", "from": "s", "to": "stt"},
        {"id": "e2", "from": "stt", "to": "show"},
    ],
}




async def clear_db(session: AsyncSession) -> None:
    # order due to FKs with CASCADE
    await session.execute(delete(Log))
    await session.execute(delete(NodeRun))
    await session.execute(delete(Run))
    await session.execute(delete(Workflow))


async def seed_db(session: AsyncSession) -> None:
    await session.execute(
        Workflow.__table__.insert(),
        [
            {
                "name": "Repo Summary (HTTP -> LLM -> Show)",
                "description": "Fetch public repo JSON and summarize with LLM, then display",
                "webhook_slug": None,
                "graph_json": WEATHER_GRAPH,
            },
            {
                "name": "Hello Show",
                "description": "Start -> Show",
                "webhook_slug": None,
                "graph_json": MINIMAL_GRAPH,
            },
            {
                "name": "Sleep Chain",
                "description": "Three sleeps in sequence to test highlighting",
                "webhook_slug": None,
                "graph_json": SLEEP_GRAPH,
            },
            {
                "name": "Agent Calculator (Start -> Agent -> Show)",
                "description": "Start query flows to agent prompt; agent uses calculator tool via tool edge",
                "webhook_slug": None,
                "graph_json": AGENT_CALC_GRAPH,
            },
            {
                "name": "Composio Gmail Joke",
                "description": "Agent generates a one‑liner and emails it via Gmail (requires Composio GMAIL connection)",
                "webhook_slug": None,
                "graph_json": COMPOSIO_GMAIL_EMAIL_GRAPH,
            },
            {
                "name": "Audio TTS → UI Audio",
                "description": "Synthesize speech and render as audio",
                "webhook_slug": None,
                "graph_json": AUDIO_TTS_GRAPH,
            },
            {
                "name": "Audio STT → Show",
                "description": "Transcribe a remote audio file and show text",
                "webhook_slug": None,
                "graph_json": AUDIO_STT_GRAPH,
            },
        ],
    )


async def main() -> None:
    confirm = os.getenv("CONFIRM_RESET")
    if confirm is None:
        try:
            ans = input("This will CLEAR workflows, runs, logs. Proceed? [y/N]: ").strip().lower()
        except EOFError:
            ans = "n"
    else:
        ans = confirm.strip().lower()

    if ans not in ("y", "yes"):
        print("Aborting. Set CONFIRM_RESET=y to bypass prompt.")
        return

    # Ensure tables exist before seeding
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        async with session.begin():
            await clear_db(session)
        async with session.begin():
            await seed_db(session)
        await session.commit()
    print("Seeded 7 workflows.")


if __name__ == "__main__":
    asyncio.run(main()) 