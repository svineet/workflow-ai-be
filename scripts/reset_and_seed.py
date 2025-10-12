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


WORKFLOW_472_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "agent", "type": "agent.react", "settings": {
            "system": "You are a helpful and slightly funny tech bro, with tools. ",
            "prompt": "Write a short one‑liner to send to , a friend I met at the MCP and AI Agents meetup with a joke about MCPs. \n\nTheir email: {{ start.data.email }}\n\nAlso send them my linkedin: https://www.linkedin.com/in/saivineet/\n\nSign it off that you're my email agent made using workflow-ai, and not me.\n\nAlso research MCP (Model Context Protocol) and produce a tiny snippet on it's history in the email. Send a nicely formatted email, use HTML compatible with email and not markdown.",
            "tools": [],
            "model": "gpt-5",
            "temperature": 1,
            "max_steps": 3,
            "timeout_seconds": 60
        }},
        {"id": "email", "type": "tool.composio", "settings": {
            "use_account": None,
            "timeout_seconds": None,
            "toolkit": "",
            "tool_slug": "GMAIL_SEND_EMAIL",
            "args": {"to": ["saivineet89+agent@gmail.com"], "subject": "A joke for you", "body": "{{ upstream.agent.final }}"}
        }},
        {"id": "start", "type": "start", "settings": {"payload": {"email": "saivineet89@gmail.com"}}},
        {"id": "show", "type": "show", "settings": {"template": "{{ upstream.agent.final }}"}},
        {"id": "tool", "type": "tool.websearch", "settings": {"name": None}},
    ],
    "edges": [
        {"id": "t1", "from": "agent", "to": "email", "kind": "tool"},
        {"id": "reactflow__edge-agent-show", "from": "agent", "to": "show", "kind": "control"},
        {"id": "reactflow__edge-start-agent", "from": "start", "to": "agent", "kind": "control"},
        {"id": "tool-agent-tool-1760178528640", "from": "agent", "to": "tool", "kind": "tool"},
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

COMPOSIO_SLACK_ANNOUNCE_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start", "settings": {"payload": {"channel": "#general"}}},
        {"id": "agent", "type": "agent.react", "settings": {
            "system": "You craft a short friendly announcement with emojis.",
            "prompt": "Announce: Workflow AI backend has new seed workflows! Keep under 25 words.",
            "model": "gpt-4o-mini",
        }},
        {"id": "slack", "type": "tool.composio", "settings": {
            "toolkit": "SLACK",
            "tool_slug": "SLACK_SEND_MESSAGE",
            "args": {"channel": "{{ start.data.channel }}", "text": "{{ upstream.agent.final }}"}
        }},
        {"id": "show", "type": "show", "settings": {"template": "Slack: {{ start.data.channel }} ← {{ upstream.agent.final }}"}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "agent"},
        {"id": "e2", "from": "agent", "to": "show"},
        {"id": "t1", "from": "agent", "to": "slack", "kind": "tool"},
    ],
}

COMPOSIO_CAL_EVENT_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start", "settings": {"payload": {"title": "Team Sync", "when": "2025-11-05T10:00:00Z"}}},
        {"id": "agent", "type": "agent.react", "settings": {
            "system": "You convert details into a calendar description.",
            "prompt": "Create a one‑sentence description for the meeting title {{ start.data.title }}.",
            "model": "gpt-4o-mini",
        }},
        {"id": "gcal", "type": "tool.composio", "settings": {
            "toolkit": "GOOGLECALENDAR",
            "tool_slug": "GOOGLECALENDAR_CREATE_EVENT",
            "args": {
                "title": "{{ start.data.title }}",
                "start_time": "{{ start.data.when }}",
                "end_time": "{{ start.data.when }}",
                "description": "{{ upstream.agent.final }}"
            }
        }},
        {"id": "show", "type": "show", "settings": {"template": "Event created: {{ start.data.title }} at {{ start.data.when }}"}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "agent"},
        {"id": "e2", "from": "agent", "to": "show"},
        {"id": "t1", "from": "agent", "to": "gcal", "kind": "tool"},
    ],
}

COMPOSIO_DRIVE_UPLOAD_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start", "settings": {"payload": {"file_url": "https://httpbin.org/image/png", "name": "logo.png"}}},
        {"id": "agent", "type": "agent.react", "settings": {
            "system": "You briefly label uploaded assets.",
            "prompt": "Generate a short one‑line label for {{ start.data.name }}.",
            "model": "gpt-4o-mini",
        }},
        {"id": "drive", "type": "tool.composio", "settings": {
            "toolkit": "GOOGLEDRIVE",
            "tool_slug": "GOOGLEDRIVE_UPLOAD_FILE",
            "args": {"name": "{{ start.data.name }}", "source_url": "{{ start.data.file_url }}", "description": "{{ upstream.agent.final }}"}
        }},
        {"id": "show", "type": "show", "settings": {"template": "Uploaded: {{ start.data.name }} with label: {{ upstream.agent.final }}"}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "agent"},
        {"id": "e2", "from": "agent", "to": "show"},
        {"id": "t1", "from": "agent", "to": "drive", "kind": "tool"},
    ],
}

WEBSEARCH_RECOMMENDATIONS_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start", "settings": {"payload": {"topic": "lightweight Python web frameworks"}}},
        {"id": "agent", "type": "agent.react", "settings": {
            "system": "You research and provide concise recommendations using a web search tool when helpful.",
            "prompt": "Find 3 modern {{ start.data.topic }} and summarize pros/cons in one sentence each.",
            "model": "gpt-4o-mini",
        }},
        {"id": "web", "type": "tool.websearch", "settings": {}},
        {"id": "show", "type": "show", "settings": {"template": "Recommendations: {{ upstream.agent.final }}"}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "agent"},
        {"id": "e2", "from": "agent", "to": "show"},
        {"id": "t1", "from": "agent", "to": "web", "kind": "tool"},
    ],
}

COMPOSIO_GMAIL_DIGEST_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start", "settings": {"payload": {"to": "saivineet89@gmail.com"}}, "position": {"x": -216.4094833108835, "y": -249.48054250668872}},
        {"id": "agent", "type": "agent.react", "settings": {
            "system": "You create a short daily digest after researching the day's news. You have tools, use them.",
            "prompt": "Create a 3‑bullet daily digest: one tech news, one productivity tip, one fun fact by searching the web. Send it to {{ start.data.to }}. ",
            "tools": [],
            "model": "gpt-5",
            "temperature": 1,
            "max_steps": 8,
            "timeout_seconds": 60
        }, "position": {"x": 214.01863306521773, "y": -2.4683786756547335}},
        {"id": "email", "type": "tool.composio", "settings": {
            "use_account": None,
            "timeout_seconds": None,
            "toolkit": "",
            "tool_slug": "GMAIL_SEND_EMAIL",
            "args": {
                "to": ["{{ start.data.to }}"],
                "subject": "Your daily mini‑digest",
                "body": "{{ upstream.agent.final }}"
            }
        }, "position": {"x": 332.23443350220447, "y": 789.2701108373118}},
        {"id": "show", "type": "show", "settings": {"template": "Digest sent to {{ start.data.to }}"}, "position": {"x": 1120.0, "y": 57.969280572757725}},
        {"id": "tool", "type": "tool.websearch", "settings": {"name": None}, "position": {"x": 807.2427226697667, "y": 722.681849540198}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "agent", "kind": "control"},
        {"id": "e2", "from": "agent", "to": "show", "kind": "control"},
        {"id": "t1", "from": "agent", "to": "email", "kind": "tool"},
        {"id": "tool-agent-tool-1760190163130", "from": "agent", "to": "tool", "kind": "tool"},
        {"id": "reactflow__edge-start-show", "from": "start", "to": "show", "kind": "control"},
    ],
}

CALENDAR_SUMMARY_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "start", "type": "start", "settings": {"payload": {"calendarId": "primary"}}, "position": {"x": 0.0, "y": 0.0}},
        {"id": "agent", "type": "agent.react", "settings": {
            "system": "You retrieve today's meetings from the user's Google Calendar and return a clear, concise summary.",
            "prompt": "Goal: Summarize all meetings scheduled TODAY on the user's Google Calendar.\n\nGuidelines:\n- Treat \"today\" as the current date at execution time in the calendar's own timezone.\n- First, get the calendar timezone for the {{ start.data.calendarId }} calendar (e.g., via CalendarList.get for 'primary'). If unavailable, default to the timezone present in event start/end data; only if neither is available, fall back to UTC.\n- Compute the day's boundaries in that timezone: 00:00:00 to 23:59:59.\n- List events for {{ start.data.calendarId }} with singleEvents=true and orderBy=startTime between timeMin and timeMax. Request enough results (e.g., maxResults=250) to cover a busy day.\n- Build a succinct summary:\n  • Date header (e.g., Saturday, October 11, 2025 – <Timezone>).\n  • Total count of meetings and total scheduled time.\n  • Chronological agenda: start–end (12‑hour with am/pm), title, organizer, top attendees (up to 5), location or conferencing link, and meeting status (e.g., accepted/needs‑action) if available.\n  • Flag overlaps/conflicts explicitly.\n  • Note all‑day events separately at the top.\n- If no meetings, state clearly that there are none today.\n- Be concise and readable.\n\nPerform the necessary tool calls and return only the final summary text.",
            "tools": [],
            "model": "gpt-4o-mini",
            "temperature": 0.2,
            "max_steps": 8,
            "timeout_seconds": 120
        }, "position": {"x": 478.66654335259375, "y": -320.77267334538925}},
        {"id": "gcal", "type": "tool.composio", "settings": {"use_account": None, "timeout_seconds": None, "toolkit": "GOOGLECALENDAR"}, "position": {"x": 109.43729127867095, "y": 788.3786399149903}},
        {"id": "show", "type": "show", "settings": {"template": "{{ upstream.agent.final }}"}, "position": {"x": 900.0, "y": 0.0}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "agent", "kind": "control"},
        {"id": "t1", "from": "agent", "to": "gcal", "kind": "tool"},
        {"id": "e2", "from": "agent", "to": "show", "kind": "control"},
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
            {
                "name": "Composio Gmail Joke (472)",
                "description": "Imported from workflow 472",
                "webhook_slug": None,
                "graph_json": WORKFLOW_472_GRAPH,
            },
            {
                "name": "Slack Announcement (Composio)",
                "description": "Agent writes an announcement; Slack tool posts to a channel",
                "webhook_slug": None,
                "graph_json": COMPOSIO_SLACK_ANNOUNCE_GRAPH,
            },
            {
                "name": "Calendar: Create Event (Composio)",
                "description": "Agent writes description and Composio creates a calendar event",
                "webhook_slug": None,
                "graph_json": COMPOSIO_CAL_EVENT_GRAPH,
            },
            {
                "name": "Drive: Upload File (Composio)",
                "description": "Upload a file from URL to Drive with a generated label",
                "webhook_slug": None,
                "graph_json": COMPOSIO_DRIVE_UPLOAD_GRAPH,
            },
            {
                "name": "Web Search Recommendations",
                "description": "Agent uses web search tool to research and summarize",
                "webhook_slug": None,
                "graph_json": WEBSEARCH_RECOMMENDATIONS_GRAPH,
            },
            {
                "name": "Daily Mini‑Digest (Gmail)",
                "description": "Agent generates a short digest and emails it",
                "webhook_slug": None,
                "graph_json": COMPOSIO_GMAIL_DIGEST_GRAPH,
            },
            {
                "name": "Calendar: Today Summary (Composio)",
                "description": "Agent summarizes today's Google Calendar using composio tools",
                "webhook_slug": None,
                "graph_json": CALENDAR_SUMMARY_GRAPH,
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
    print("Seeded 12 workflows.")


if __name__ == "__main__":
    asyncio.run(main()) 