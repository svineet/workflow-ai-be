from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from openai import AsyncOpenAI

from ..registry import register, run_block
from ..base import Block, RunContext
from ...server.settings import settings
from ...services.composio import get_composio_openai_agents_client


class AgentToolSpec(BaseModel):
    name: str = Field(...)
    type: str = Field(...)
    settings: Dict[str, Any] = Field(default_factory=dict)


class AgentReactSettings(BaseModel):
    system: Optional[str] = Field(default="You are a helpful assistant. Use tools when needed.")
    prompt: Optional[str] = Field(default=None)
    tools: Optional[List[AgentToolSpec]] = Field(default=None)
    model: Optional[str] = Field(default="gpt-4o-mini")
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    max_steps: int = Field(default=8, ge=1, le=32)
    timeout_seconds: float = Field(default=60.0, ge=1.0)


class AgentReactOutput(BaseModel):
    final: str
    trace: List[Dict[str, Any]]


@register("agent.react")
class AgentReactBlock(Block):
    type_name = "agent.react"
    kind = "agent"
    summary = "Agent powered by OpenAI Agents SDK with Composio tool execution"
    settings_model = AgentReactSettings
    output_model = AgentReactOutput

    @classmethod
    def extras(cls) -> Dict[str, Any]:
        return {
            "connectors": [
                {
                    "name": "tools",
                    "display_name": "Tools",
                    "kind": "tool-connector",
                    "multiple": True,
                    "accepts": ["tool"],
                    "description": "Connect tool blocks to be available to the agent",
                }
            ]
        }

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        system = s.get("system") or "You are a helpful assistant. Use tools when needed."
        prompt_single: Optional[str] = s.get("prompt")
        if prompt_single is None or not str(prompt_single).strip():
            raise ValueError("agent.react requires 'prompt'")

        node_id = input.get("node_id")
        await ctx.logger(
            "agent.react(openai_agents): start",
            {"model": s.get("model") or "gpt-4o-mini", "temperature": float(s.get("temperature", 1))},
            node_id=node_id,
        )

        # Build toolkits and composio tool slugs from tool edges (agent -> tool.*)
        derived_tools = input.get("__derived_tools_from_edges__") or []
        toolkit_hints: List[str] = []
        tool_slugs: List[str] = []
        non_composio_tools: List[Dict[str, Any]] = []
        for t in derived_tools:
            try:
                ttype = str((t or {}).get("type", ""))
                if ttype.startswith("tool.composio"):
                    tk = (t.get("settings") or {}).get("toolkit")
                    slug = (t.get("settings") or {}).get("tool_slug")
                    if tk and tk not in toolkit_hints:
                        toolkit_hints.append(tk)
                    if isinstance(slug, str) and slug:
                        tool_slugs.append(slug)
                else:
                    non_composio_tools.append(t)
            except Exception:
                pass

        # If we have any non-Composio tools (e.g. tool.calculator), fallback to internal ReAct loop for those
        if non_composio_tools:
            return await self._run_internal_tools_react(system, prompt_single, non_composio_tools, input, ctx)

        composio_agents = get_composio_openai_agents_client()
        if composio_agents is None:
            raise ValueError("Composio OpenAI Agents provider is not available. Ensure composio-openai-agents is installed and COMPOSIO_API_KEY is set.")

        # Fetch Composio tools by toolkits and by specific slugs, then merge (docs: combinations are exclusive)
        tools: List[Dict[str, Any]] = []
        try:
            if toolkit_hints:
                tk_tools = composio_agents.tools.get(user_id="system-user", toolkits=toolkit_hints)
                if isinstance(tk_tools, list):
                    tools.extend(tk_tools)
            if tool_slugs:
                slug_tools = composio_agents.tools.get(user_id="system-user", tools=tool_slugs)
                if isinstance(slug_tools, list):
                    tools.extend(slug_tools)
            # If nothing fetched but we have neither hints nor slugs, fall back to env-configured toolkits
            if not tools and not (toolkit_hints or tool_slugs):
                env_tools = composio_agents.tools.get(user_id="system-user", toolkits=settings.COMPOSIO_TOOLKITS)
                if isinstance(env_tools, list):
                    tools.extend(env_tools)
        except Exception as ex:
            await ctx.logger("agent.react(openai_agents): failed to load tools", {"error": str(ex)}, node_id=node_id)
            tools = []

        await ctx.logger(
            "agent.react(openai_agents): tools prepared",
            {"num_tools": len(tools), "toolkits": toolkit_hints, "tool_slugs": tool_slugs},
            node_id=node_id,
        )

        # Create and run the OpenAI Agent with Composio tools
        try:
            from agents import Agent, Runner  # type: ignore
        except Exception as ex:
            raise ValueError(f"OpenAI Agents SDK not available: {ex}")

        agent = Agent(
            name="Agent",
            instructions=str(system),
            model=s.get("model") or "gpt-5",
            tools=tools,
        )

        try:
            result = await Runner.run(starting_agent=agent, input=str(prompt_single))
        except Exception as ex:
            await ctx.logger("agent.react(openai_agents): run error", {"error": str(ex)}, node_id=node_id)
            raise

        final_text = getattr(result, "final_output", None)
        if not isinstance(final_text, str):
            try:
                final_text = json.dumps(final_text, ensure_ascii=False)
            except Exception:
                final_text = str(final_text)

        await ctx.logger("agent.react(openai_agents): final", {"final_preview": (final_text or "")[:300]}, node_id=node_id)
        return AgentReactOutput(final=final_text or "", trace=[{"provider": "openai_agents", "toolkits": toolkit_hints, "tool_slugs": tool_slugs}]).model_dump()

    async def _run_internal_tools_react(self, system: str, prompt: str, tool_nodes: List[Dict[str, Any]], agent_input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        """Fallback ReAct loop to support non-Composio local tools (e.g., tool.calculator)."""
        model = (self.settings.get("model") or "gpt-4o-mini")
        temperature = float(self.settings.get("temperature", 1))
        max_steps = int(self.settings.get("max_steps", 6))
        node_id = agent_input.get("node_id")
        upstream_ctx = agent_input.get("upstream") or {}

        # Build tools_spec from tool_nodes
        tools_spec: List[Dict[str, Any]] = []
        for t in tool_nodes:
            name = t.get("name") or t.get("id") or t.get("type")
            tools_spec.append({"name": str(name), "type": t.get("type"), "settings": t.get("settings") or {}})

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        try:
            messages: List[Dict[str, Any]] = []
            if system:
                messages.append({"role": "system", "content": system + "\nUse tools when needed. Reply with ReAct format."})
            messages.append({"role": "user", "content": str(prompt)})

            for step in range(1, max_steps + 1):
                completion = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                )
                msg = completion.choices[0].message.content or ""
                await ctx.logger("agent.react(fallback): step", {"step": step, "assistant_preview": msg[:300]}, node_id=node_id)

                final_match = re.search(r"Final Answer:\s*(.*)", msg, re.IGNORECASE | re.DOTALL)
                if final_match:
                    final_text = final_match.group(1).strip()
                    return AgentReactOutput(final=final_text, trace=[{"step": step}]).model_dump()

                action_match = re.search(r"Action:\s*([^\n]+)\nAction Input:\s*(.*)", msg, re.IGNORECASE | re.DOTALL)
                if action_match:
                    tool_name = action_match.group(1).strip()
                    raw_input = action_match.group(2).strip()
                    try:
                        tool_input = json.loads(raw_input)
                    except Exception:
                        tool_input = raw_input

                    spec = next((t for t in tools_spec if t.get("name") == tool_name), None)
                    if not spec:
                        messages.append({"role": "user", "content": f"Observation: Unknown tool {tool_name}"})
                        continue
                    block_type = spec.get("type")
                    base_settings = spec.get("settings") or {}
                    merged_settings = dict(base_settings)
                    if isinstance(tool_input, dict):
                        merged_settings.update(tool_input)
                    else:
                        if "expression" in base_settings or str(block_type).endswith("calculator"):
                            merged_settings["expression"] = str(tool_input)
                        else:
                            merged_settings["input"] = tool_input

                    tool_run_input: Dict[str, Any] = {
                        "settings": merged_settings,
                        "upstream": upstream_ctx,
                        "trigger": agent_input.get("trigger") or {},
                        "node_id": f"{node_id}::tool::{tool_name}",
                    }
                    await ctx.logger("agent.react(fallback): invoking tool", {"tool": tool_name}, node_id=node_id)
                    result = await run_block(block_type, tool_run_input, ctx)
                    obs = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
                    messages.append({"role": "user", "content": f"Observation: {obs}"})
                    continue

                messages.append({"role": "user", "content": "Please provide Final Answer."})

            return AgentReactOutput(final="Failed to reach a final answer within max_steps.", trace=[]).model_dump()
        finally:
            await client.close() 