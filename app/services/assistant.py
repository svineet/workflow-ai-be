from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
import logging
from typing import Any, Dict, List, Optional, Tuple

import openai
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.graph import Graph
from ..server.settings import settings
from ..db.models import Workflow


CACHE_ENABLED = True
_ASSISTANT_LRU_CAPACITY = 64
_assistant_cache: OrderedDict[str, int] = OrderedDict()
_assistant_cache_lock = asyncio.Lock()

logger = logging.getLogger("assistant")


def _assistant_system_prompt() -> str:
    return (
        """
You design executable workflow graphs for a fixed block engine.

Return ONLY a strict JSON object with exactly these top-level keys:
{
  "nodes": [ { "id": string, "type": string, "settings": object } ],
  "edges": [ { "id": string, "from": string, "to": string, "kind": optional("control"|"tool") } ]
}

Hard rules:
- IDs must be unique.
- Use ONLY these block types (exact type ids):
  start, show, agent.react, tool.composio, tool.calculator,
  llm.simple, web.get, http.request,
  audio.tts, audio.stt, ui.audio,
  transform.template, json.get
- Edges are simple and linear: no ports, just "from" node id to "to" node id.
- DO NOT include any "route" or custom fields on edges.
- Use 'kind': 'tool' ONLY when connecting an agent to a tool node (agent.react -> tool.*). All other edges omit 'kind' (or use 'control').
- Prefer minimal linear flows. Add nodes only when the user request explicitly needs them.
- If the user gives inputs (topic/emails/links), put them in start.settings.payload.
- Use Jinja placeholders in settings where appropriate (e.g., "{{ start.data.topic }}").
- Always end with a 'show' node that surfaces the outcome (e.g., final text, useful links, or a short trace).

Templating:
- Use Jinja placeholders in settings where appropriate (e.g., "{{ start.data.topic }}").
- To reference data from a start node, use {{ start_node_id.data.<variabel_name> }}, with the start node connected to the block.
- In the show node, all variables from inbound connected edges are provided as {{ upstream.node_id.<whatever> }} 
- In general, for any node, you can reference variables from inbound connected edges as {{ node_id.<whatever> }}

Block catalog (compact):

- start — emit provided payload (settings: { payload?: object })
- show — UI sink, can render Markdown (settings: { template?: string })
- agent.react — tool-using LLM step
  settings: {
    system?: string,
    prompt?: string,            # optional extra instruction merged with system; you may also inline everything into messages if you prefer
    tools?: [{ name:string, type:string, settings?:object }],  # usually Composio tools exposed to the agent
    model?: string (default gpt-5),
    temperature?: number,
    max_steps?: integer (default 8),
    timeout_seconds?: number (default 60)
  }
  output: { final: string, trace: object[] }


- llm.simple — single LLM completion (settings: { prompt: string, model?: string })
- web.get — HTTP with parsing (settings: { url: string, method?: "GET", headers?: object, body?: any, follow_redirects?: boolean, timeout_seconds?: number, response_mode?: "auto"|"json"|"text"|"bytes" })
- http.request — low-level HTTP (settings: { method: string, url: string, headers?: object, body?: any, follow_redirects?: boolean, timeout_seconds?: number })
- audio.tts — text→speech (settings: { text: string, model?: "tts-1", voice?: "alloy", format?: "mp3"|"wav", timeout_seconds?: number })
- audio.stt — speech→text (settings: { media: any, model?: "whisper-1", timeout_seconds?: number, prompt?: string|null, language?: string|null })
- ui.audio — UI audio player (settings: { file: any, title?: string })
- transform.template — Jinja templating (settings: { template: string, values?: object })
- json.get — extract nested value (settings: { path: string[], source?: object|null })

## Tool nodes:
These are the tools that the agent can use. Connect them to `agent.react` with an edge of kind `tool` to make the tool available to the agent.

- tool.composio — Call a specific Composio tool directly
  settings: {
    toolkit: string,            # e.g., "GMAIL", "GOOGLECALENDAR"
    tool_slug: string,          # e.g., "GMAIL_SEND_EMAIL", "GOOGLECALENDAR_CREATE_EVENT"
    use_account?: string,       # optional connected account id
    args?: object,              # tool arguments (can use Jinja from upstream)
    timeout_seconds?: number
  }
  Prefer specifying a concrete `tool_slug`. Skipping `tool_slug` may expose an entire toolkit; avoid unless necessary.
  IF YOU KNOW THE TOOL SLUG, USE IT, AND DO NOT FILL THE TOOLKIT PARAMETER.

- tool.calculator — Evaluate a basic arithmetic expression
- tool.http_request — Perform an HTTP request via the backend
- tool.websearch — Hosted web search tool (OpenAI Agents SDK)
- tool.code_interpreter — Hosted code interpreter (OpenAI Agents SDK)


Design guidelines:
- Use agent.react for any task requiring reasoning or multiple steps; include the minimum necessary tool access in settings.tools (e.g., "tool.composio" with a specific tool_slug).
- Feel free to compose agents together, using specialised agents for smaller tasks/steps. Example: Research agent -> Email agent.
- Prefer agents with web search attached as a tool, over simple web.get or HTTP request blocks.
- Prompting: Agent prompts shoudl indicate what actions are expected of the agent. Tell it to execute what you need it to do.
- For audio previews, chain llm/simple text -> audio.tts -> ui.audio (or show).
- Keep settings small and explicit; do not invent fields not in the catalog.
- DO NOT HALLUCINATE URLS for web.get or http.request blocks. Instead make agents, they will do the reasoning,
and discovery of the data themselves.
- Email agents should be prompted to send emails in HTML, not markdown.
- Show block renders markdown.

To Remember:
- To access data from a block, we must have an edge going out from the previous block to the block we want to access the data from.
- Remember this while writing the template for parameters in the blocks.
- Tool nodes do not support input or output parameters, they only connect to agent nodes,
and the agent node will call the tool. Avoid templates for tool nodes if possible.
- If confused about a composio tool, web search to find the tool slug. In general, all integrations are exposed as tools in Composio, like Slack, Gmail, GCalendar, etc.

Reflection step:
- Once generated, reflect on the graph and make sure it is correct.
- Connect edges according to data usage.
- Verify the templating and settings, and tools for agent blocks.
- Make sure all agents have required tools attached to them, according to their prompt.

Finally, return JSON only for the final workflow. No comments, no markdown, no backticks.

### Examples

- Example 1 — LLM joke generator → send via Gmail (Composio)

```json
{
  "nodes": [
    { "id": "start", "type": "start", "settings": { "payload": { "email": "friend@example.com" } } },
    { "id": "agent", "type": "agent.react", "settings": {
      "system": "You write a single‑line programming joke.",
      "prompt": "Write a short, clean one‑liner programming joke.",
      "model": "gpt-5-mini"
    }},
    { "id": "email", "type": "tool.composio", "settings": {
      "toolkit": "GMAIL",
      "tool_slug": "GMAIL_SEND_EMAIL",
      "args": {
        "to": ["{{ start.data.email }}"],
        "subject": "A quick joke for you",
        "body": "{{ upstream.agent.final }}"
      }
    }},
    { "id": "show", "type": "show", "settings": { "template": "Joke sent to {{ start.data.email }}: {{ upstream.agent.final }}" } }
  ],
  "edges": [
    { "id": "e1", "from": "start", "to": "agent" },
    { "id": "e2", "from": "agent", "to": "show" },
    { "id": "e3", "from": "start", "to": "show" },
    { "id": "t1", "from": "agent", "to": "email", "kind": "tool" }
  ]
}
```

- Example 2 — Fetch repo → summarize → show

```json
{
  "nodes": [
    { "id": "get", "type": "http.request", "settings": { "method": "GET", "url": "https://api.github.com/repos/python/cpython", "headers": { "Accept": "application/vnd.github+json" } } },
    { "id": "summ", "type": "llm.simple", "settings": { "prompt": "Summarize key facts about this repository: {{ get.data }}", "model": "gpt-4o-mini" } },
    { "id": "show", "type": "show", "settings": { "template": "Summary: {{ upstream.summ.text }}" } }
  ],
  "edges": [
    { "id": "e1", "from": "get", "to": "summ" },
    { "id": "e2", "from": "summ", "to": "show" }
  ]
}
```

- Example 3 — Agent with web search tool

```json
{
  "nodes": [
    { "id": "start", "type": "start", "settings": { "payload": { "query": "Best coffee shops in SF" } } },
    { "id": "agent", "type": "agent.react", "settings": {
      "system": "You research and provide concise recommendations using the web search tool when helpful.",
      "prompt": "Find 3 highly rated coffee shops near downtown SF and explain briefly why.",
      "model": "gpt-5"
    }},
    { "id": "web", "type": "tool.websearch", "settings": { } },
    { "id": "show", "type": "show", "settings": { "template": "Results: {{ upstream.agent.final }}" } }
  ],
  "edges": [
    { "id": "e1", "from": "start", "to": "agent" },
    { "id": "e2", "from": "agent", "to": "show" },
    { "id": "t1", "from": "agent", "to": "web", "kind": "tool" }
  ]
}
```

- Example 4 — Slack Announcement (Composio)

```json
{
  "nodes": [
    { "id": "start", "type": "start", "settings": { "payload": { "channel": "#general" } } },
    { "id": "agent", "type": "agent.react", "settings": {
      "system": "You craft a short friendly announcement with emojis.",
      "prompt": "Announce: Workflow AI backend has new seed workflows! Keep under 25 words. Post it to Slack in any channel. Report what you did.",
      "model": "gpt-5"
    }},
    { "id": "slack", "type": "tool.composio", "settings": {
      "toolkit": "SLACK",
      "tool_slug": "SLACK_SEND_MESSAGE",
      "args": {"channel": "{{ start.data.channel }}", "text": "{{ upstream.agent.final }}"}
    }},
    { "id": "show", "type": "show", "settings": { "template": "Slack: {{ start.data.channel }} ← {{ upstream.agent.final }}" } }
  ],
  "edges": [
    { "id": "e1", "from": "start", "to": "agent" },
    { "id": "e2", "from": "agent", "to": "show" },
    { "id": "e3", "from": "start", "to": "show" },
    { "id": "t1", "from": "agent", "to": "slack", "kind": "tool" }
  ]
}
```

- Example 5 — Calendar: Create Event (Composio)

```json
{
  "nodes": [
    { "id": "start", "type": "start", "settings": { "payload": { "title": "Team Sync", "when": "2025-11-05T10:00:00Z" } } },
    { "id": "agent", "type": "agent.react", "settings": {
      "system": "You convert details into a calendar description.",
      "prompt": "Create a one‑sentence description for the meeting title {{ start.data.title }}.",
      "model": "gpt-5"
    }},
    { "id": "gcal", "type": "tool.composio", "settings": {
      "toolkit": "GOOGLECALENDAR",
      "tool_slug": "GOOGLECALENDAR_CREATE_EVENT",
      "args": {
        "title": "{{ start.data.title }}",
        "start_time": "{{ start.data.when }}",
        "end_time": "{{ start.data.when }}",
        "description": "{{ upstream.agent.final }}"
      }
    }},
    { "id": "show", "type": "show", "settings": { "template": "Event created: {{ start.data.title }} at {{ start.data.when }}" } }
  ],
  "edges": [
    { "id": "e1", "from": "start", "to": "agent" },
    { "id": "e2", "from": "agent", "to": "show" },
    { "id": "e3", "from": "start", "to": "show" },
    { "id": "t1", "from": "agent", "to": "gcal", "kind": "tool" }
  ]
}
```

"""
    )


def _extract_json_object(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    fence = re.search(r"```json\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
    raise ValueError("Unable to extract JSON graph from model output")


async def _generate_graph_from_prompt(prompt: str, model: Optional[str]) -> Dict[str, Any]:
    fallback_graph: Dict[str, Any] = {
        "nodes": [
            {"id": "start", "type": "start", "settings": {"payload": {"prompt": prompt}}},
            {"id": "show", "type": "show", "settings": {"template": "Created from prompt: {{ start.data['prompt'] }}"}},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "show"},
        ],
    }
    logger.info(
        "assistant.generate: starting OpenAI call",
        extra={"model": model or "gpt-4o-mini", "prompt_preview": (prompt or "")[:200]},
    )

    if not settings.OPENAI_API_KEY:
        logger.warning("assistant.generate: OPENAI_API_KEY missing, returning fallback graph")
        return fallback_graph

    # Prefer OpenAI Agents SDK
    try:
        from agents import Agent, Runner, WebSearchTool  # type: ignore
    except Exception:
        logger.exception("assistant.generate: OpenAI Agents SDK not available; returning fallback graph")
        return fallback_graph

    sys_prompt = _assistant_system_prompt()
    chosen_model = (model or "gpt-5")
    tools = [WebSearchTool()]
    agent = Agent(name="WorkflowDesigner", instructions=sys_prompt, model=chosen_model, tools=tools)

    try:
        result = await Runner.run(starting_agent=agent, input=prompt)
        content = getattr(result, "final_output", None)
        if not isinstance(content, str):
            try:
                content = json.dumps(content)
            except Exception:
                content = str(content)
        logger.info(
            "assistant.generate: agents sdk result",
            extra={"model": chosen_model, "content_len": len(content or ""), "content_preview": (content or "")[:300]},
        )
        if not content or not content.strip():
            logger.warning("assistant.generate: empty final_output; returning fallback graph")
            return fallback_graph
        try:
            obj = _extract_json_object(content)
        except Exception:
            logger.exception("assistant.generate: failed to extract JSON from agents output; returning fallback graph")
            return fallback_graph
        if not isinstance(obj, dict):
            logger.warning("assistant.generate: non-dict JSON root; returning fallback graph")
            return fallback_graph
        obj.setdefault("nodes", [])
        obj.setdefault("edges", [])
        logger.info("assistant.generate: parsed graph", extra={"num_nodes": len(obj.get("nodes", [])), "num_edges": len(obj.get("edges", []))})
        return obj
    except Exception:
        logger.exception("assistant.generate: agents sdk run failed; returning fallback graph")
        return fallback_graph


async def stream_graph_from_prompt(session: AsyncSession, prompt: str, model: Optional[str], *, user_id: Optional[str] = None):
    """Async generator that streams agent events and yields JSON envelopes for SSE.

    Yields dicts with keys: type, data
    Types:
      - status {stage}
      - agent_event {preview}
      - final_graph {graph}
      - workflow_created {id}
      - error {message}
    """
    # Start
    yield {"type": "status", "stage": "starting"}
    if not settings.OPENAI_API_KEY:
        yield {"type": "error", "message": "OPENAI_API_KEY missing"}
        return

    try:
        from agents import Agent, Runner, WebSearchTool, ItemHelpers  # type: ignore
        from openai.types.responses import ResponseTextDeltaEvent
    except Exception as ex:
        yield {"type": "error", "message": f"Agents SDK unavailable: {ex}"}
        return

    sys_prompt = _assistant_system_prompt()
    chosen_model = (model or "gpt-5")
    tools = [WebSearchTool()]
    agent = Agent(name="WorkflowDesigner", instructions=sys_prompt, model=chosen_model, tools=tools)

    # Stream agent run
    final_text_chunks: List[str] = []
    final_text_from_item: Optional[str] = None
    try:
        result = Runner.run_streamed(starting_agent=agent, input=prompt)
        async for evt in result.stream_events():
            try:
                if evt.type == "raw_response_event":
                    if isinstance(evt.data, ResponseTextDeltaEvent):
                        delta = evt.data.delta
                        if delta:
                            final_text_chunks.append(delta)
                            yield {"type": "agent_event", "preview": delta}
                elif evt.type == "run_item_stream_event":
                    if evt.item.type == "message_output_item":
                        final_text_from_item = ItemHelpers.text_message_output(evt.item)
                        yield {"type": "agent_event", "preview": "Agent thought..."}
                    elif evt.item.type == "tool_call_item":
                        tool_name = getattr(evt.item, "name", "tool")
                        yield {"type": "agent_event", "preview": f"Calling tool: `{tool_name}`..."}
                    elif evt.item.type == "tool_call_output_item":
                        yield {"type": "agent_event", "preview": "Tool call finished."}
            except Exception:
                # Ignore serialization issues; keep streaming
                pass
    except Exception as ex:
        yield {"type": "error", "message": f"agent_stream_error: {ex}"}
        return

    # Produce final graph
    final_text = final_text_from_item if final_text_from_item is not None else "".join(final_text_chunks).strip()
    if not final_text:
        # Fallback to non‑stream generation in worst case
        graph = await _generate_graph_from_prompt(prompt, model)
    else:
        try:
            graph = _extract_json_object(final_text)
        except Exception:
            graph = await _generate_graph_from_prompt(prompt, model)

    try:
        graph_obj = Graph.model_validate(graph)
        gdict = _normalize_agent_tools(graph_obj.model_dump(by_alias=True))
    except Exception as ex:
        yield {"type": "error", "message": f"graph_validation_failed: {ex}"}
        return

    yield {"type": "final_graph", "graph": gdict}

    # Persist workflow
    try:
        # Cheap title/description
        name = (prompt[:60] + ("…" if len(prompt) > 60 else "")).strip()
        description = f"Seeded from assistant: {prompt[:200]}".strip()
        result = await session.execute(
            insert(Workflow).values(name=name or "Assistant workflow", description=description, webhook_slug=None, graph_json=gdict, user_id=user_id)
        )
        await session.commit()
        workflow_id = int(result.inserted_primary_key[0])
        yield {"type": "workflow_created", "id": workflow_id}
    except Exception as ex:
        yield {"type": "error", "message": f"persist_failed: {ex}"}

def _is_tool_compatible(type_name: str) -> bool:
    from ..blocks.registry import get_block_class

    cls = get_block_class(type_name)
    if cls is None:
        return False
    if getattr(cls, "tool_compatible", False):
        return True
    if type_name.startswith("tool."):
        return True
    extras = cls.extras() if hasattr(cls, "extras") and callable(getattr(cls, "extras")) else None
    if isinstance(extras, dict) and extras.get("toolCompatible") is True:
        return True
    return False


def _normalize_agent_tools(gdict: Dict[str, Any]) -> Dict[str, Any]:
    from ..blocks.registry import get_block_class

    for node in gdict.get("nodes", []):
        type_name = node.get("type")
        cls = get_block_class(type_name)
        is_agent = (type_name or "").startswith("agent.") or (cls is not None and getattr(cls, "kind", "") == "agent")
        if not is_agent:
            continue
        settings = node.get("settings") or {}
        tools = settings.get("tools") or []
        seen: set[str] = set()
        normalized_tools: list[Dict[str, Any]] = []
        for t in tools:
            tname = (t or {}).get("name")
            ttype = (t or {}).get("type")
            tsettings = (t or {}).get("settings") or {}
            if not tname or not isinstance(tname, str):
                raise ValueError(f"Agent node {node.get('id')}: tool missing valid 'name'")
            if tname in seen:
                raise ValueError(f"Agent node {node.get('id')}: duplicate tool name '{tname}'")
            seen.add(tname)
            if not ttype or not isinstance(ttype, str):
                raise ValueError(f"Agent node {node.get('id')}: tool '{tname}' missing valid 'type'")
            if not _is_tool_compatible(ttype):
                raise ValueError(f"Agent node {node.get('id')}: tool '{tname}' type '{ttype}' is not recognized as tool-compatible")
            tcls = get_block_class(ttype)
            if tcls is None:
                raise ValueError(f"Agent node {node.get('id')}: unknown tool type '{ttype}'")
            Model = getattr(tcls, "settings_model", None)
            if Model is not None:
                validated = Model.model_validate(tsettings)
                tsettings = validated.model_dump()
            normalized_tools.append({"name": tname, "type": ttype, "settings": tsettings})
        settings["tools"] = normalized_tools
        node["settings"] = settings
    return gdict


async def create_workflow_from_prompt(session: AsyncSession, prompt: str, model: Optional[str], *, user_id: Optional[str] = None) -> Tuple[int, bool]:
    prompt_key = (prompt or "").strip()
    if not prompt_key:
        raise ValueError("prompt is required")

    async with _assistant_cache_lock:
        cached = _assistant_cache.get(prompt_key)
        if cached is not None and CACHE_ENABLED:
            _assistant_cache.move_to_end(prompt_key)
            logger.info("assistant.create: cache hit", extra={"workflow_id": int(cached)})
            await asyncio.sleep(5)

            return int(cached), True


    async def _summarise_prompt_with_openai(prompt: str) -> Tuple[str, str]:
        """Best-effort summarization for name/description. Must not fail the request."""
        try:
            client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Given a user input describing a workflow, return a JSON object with keys 'title' (<=5 words) and 'description' (one sentence)."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=120,
            )
            raw = getattr(resp.choices[0].message, "content", None)
            data = json.loads(raw) if isinstance(raw, str) else {}
            title = str((data or {}).get("title") or "").strip()
            description = str((data or {}).get("description") or "").strip()
            if not title:
                title = (prompt[:60] + ("…" if len(prompt) > 60 else "")).strip()
            if not description:
                description = f"Seeded from assistant: {prompt[:200]}".strip()
            return title, description
        except Exception:
            # Never fail the whole operation due to naming; fallback
            title = (prompt[:60] + ("…" if len(prompt) > 60 else "")).strip()
            description = f"Seeded from assistant: {prompt[:200]}".strip()
            return title, description

    # Run both graph generation and title/description summarization in parallel
    raw_graph_task = asyncio.create_task(_generate_graph_from_prompt(prompt, model))
    summary_task = asyncio.create_task(_summarise_prompt_with_openai(prompt))

    raw_graph, (name, description) = await asyncio.gather(raw_graph_task, summary_task, return_exceptions=True)
    description = description or f"Seeded from assistant: {prompt_key[:200]}".strip()
    logger.info(
        "assistant.create: raw graph generated",
        extra={"num_nodes": len((raw_graph or {}).get("nodes", [])), "num_edges": len((raw_graph or {}).get("edges", []))},
    )

    graph_obj = Graph.model_validate(raw_graph)
    gdict = _normalize_agent_tools(graph_obj.model_dump(by_alias=True))

    stmt = insert(Workflow).values(
        name=name or "Assistant workflow",
        description=description,
        webhook_slug=None,
        graph_json=gdict,
        user_id=user_id,
    )
    result = await session.execute(stmt)
    await session.commit()
    new_id = int(result.inserted_primary_key[0])
    logger.info("assistant.create: workflow persisted", extra={"workflow_id": new_id})

    async with _assistant_cache_lock:
        _assistant_cache[prompt_key] = new_id
        if len(_assistant_cache) > _ASSISTANT_LRU_CAPACITY:
            _assistant_cache.popitem(last=False)

    return new_id, False


