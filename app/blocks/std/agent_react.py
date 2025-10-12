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
        system_raw = s.get("system") or "You are a helpful assistant. Use tools when needed."
        prompt_single: Optional[str] = s.get("prompt")
        if prompt_single is None or not str(prompt_single).strip():
            raise ValueError("agent.react requires 'prompt'")

        # Render Jinja templates for system and prompt using upstream + extra context
        upstream_ctx = input.get("upstream") or {}
        extra_ctx = {"settings": s, "trigger": input.get("trigger") or {}, "upstream": upstream_ctx}
        try:
            system = self.render_expression(str(system_raw), upstream=upstream_ctx, extra=extra_ctx)
        except Exception:
            system = str(system_raw)
        try:
            rendered_prompt = self.render_expression(str(prompt_single), upstream=upstream_ctx, extra=extra_ctx)
        except Exception:
            rendered_prompt = str(prompt_single)

        node_id = input.get("node_id")
        await ctx.logger(
            "agent.react(openai_agents): start",
            {"model": s.get("model") or "gpt-4o-mini", "temperature": float(s.get("temperature", 1)), "prompt_preview": str(rendered_prompt)[:200]},
            node_id=node_id,
        )

        # Gather tools from edges
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

        # Fetch Composio tools by toolkits and by specific slugs, then merge
        tools: List[Any] = []
        if toolkit_hints or tool_slugs:
            composio_agents = get_composio_openai_agents_client()
            if composio_agents is None:
                raise ValueError("Composio OpenAI Agents provider is not available. Ensure composio-openai-agents is installed and COMPOSIO_API_KEY is set.")
            try:
                if toolkit_hints:
                    tk_tools = composio_agents.tools.get(user_id="system-user", toolkits=toolkit_hints)
                    if isinstance(tk_tools, list):
                        tools.extend(tk_tools)
                    await ctx.logger(
                        "agent.react(openai_agents): fetched tools by toolkits",
                        {"count": len(tk_tools) if isinstance(tk_tools, list) else 0, "toolkits": toolkit_hints},
                        node_id=node_id,
                    )
                if tool_slugs:
                    slug_tools = composio_agents.tools.get(user_id="system-user", tools=tool_slugs)
                    if isinstance(slug_tools, list):
                        tools.extend(slug_tools)
                    await ctx.logger(
                        "agent.react(openai_agents): fetched tools by slugs",
                        {"count": len(slug_tools) if isinstance(slug_tools, list) else 0, "slugs": tool_slugs},
                        node_id=node_id,
                    )
                if not tools and not (toolkit_hints or tool_slugs):
                    env_tools = composio_agents.tools.get(user_id="system-user", toolkits=settings.COMPOSIO_TOOLKITS)
                    if isinstance(env_tools, list):
                        tools.extend(env_tools)
                    await ctx.logger(
                        "agent.react(openai_agents): fetched tools from env toolkits",
                        {"count": len(env_tools) if isinstance(env_tools, list) else 0, "toolkits": settings.COMPOSIO_TOOLKITS},
                        node_id=node_id,
                    )
            except Exception as ex:
                await ctx.logger(
                    "agent.react(openai_agents): failed to load tools",
                    {"error": str(ex), "toolkits": toolkit_hints, "slugs": tool_slugs},
                    node_id=node_id,
                )
                tools = []

        # Convert non-Composio tool nodes to Agents SDK tools
        if non_composio_tools:
            try:
                from agents import FunctionTool, WebSearchTool, CodeInterpreterTool  # type: ignore
            except Exception as ex:
                await ctx.logger("agent.react(openai_agents): failed to import tool classes", {"error": str(ex)}, node_id=node_id)
                # Fallback to internal ReAct for non-Composio if Agents SDK tools unavailable
                return await self._run_internal_tools_react(system, rendered_prompt, non_composio_tools, input, ctx)

            # Define function tools mapping
            def build_calculator_tool() -> Any:
                async def on_invoke(ctx_wrap, args_json: str) -> str:  # type: ignore
                    try:
                        data = json.loads(args_json) if args_json else {}
                    except Exception:
                        data = {"expression": args_json}
                    if not isinstance(data, dict):
                        data = {"expression": str(data)}
                    merged_settings = {"expression": data.get("expression")}
                    tool_run_input: Dict[str, Any] = {
                        "settings": merged_settings,
                        "upstream": input.get("upstream") or {},
                        "trigger": input.get("trigger") or {},
                        "node_id": f"{node_id}::tool::calculator",
                    }
                    result = await run_block("tool.calculator", tool_run_input, ctx)
                    return json.dumps(result, ensure_ascii=False)

                schema = {
                    "title": "calculator_args",
                    "type": "object",
                    "properties": {"expression": {"type": "string", "description": "Arithmetic expression"}},
                    "required": ["expression"],
                }

                return FunctionTool(
                    name="calculator",
                    description="Evaluate arithmetic expressions",
                    params_json_schema=schema,
                    on_invoke_tool=on_invoke,
                )

            def build_http_tool() -> Any:
                async def on_invoke(ctx_wrap, args_json: str) -> str:  # type: ignore
                    # Expect args_json to match http.request settings (method,url,headers,body,...)
                    try:
                        settings_in = json.loads(args_json) if args_json else {}
                    except Exception:
                        settings_in = {}
                    tool_run_input: Dict[str, Any] = {
                        "settings": settings_in,
                        "upstream": input.get("upstream") or {},
                        "trigger": input.get("trigger") or {},
                        "node_id": f"{node_id}::tool::http_request",
                    }
                    result = await run_block("http.request", tool_run_input, ctx)
                    return json.dumps(result, ensure_ascii=False)

                params = {
                    "title": "http_request_args",
                    "type": "object",
                    "properties": {
                        "method": {"type": "string"},
                        "url": {"type": "string"},
                        "headers": {"type": "object"},
                        "body": {"type": ["string", "object", "null"]},
                        "timeout_seconds": {"type": ["number", "null"]},
                    },
                    "required": ["url"],
                }
                return FunctionTool(
                    name="http_request",
                    description="Perform an HTTP request and return status, headers, data",
                    params_json_schema=params,
                    on_invoke_tool=on_invoke,
                )

            # Hosted tools
            def build_websearch_tool() -> Any:
                return WebSearchTool()

            def build_code_interpreter_tool() -> Any:
                return CodeInterpreterTool()

            # From non_composio_tools list, attach corresponding tool instances
            type_to_builder = {
                "tool.calculator": build_calculator_tool,
                "tool.http_request": build_http_tool,
                "tool.websearch": build_websearch_tool,
                "tool.code_interpreter": build_code_interpreter_tool,
            }

            for t in non_composio_tools:
                t_type = str(t.get("type") or "")
                builder = type_to_builder.get(t_type)
                if builder is None:
                    continue
                try:
                    tool_obj = builder()
                    tools.append(tool_obj)
                except Exception as ex:
                    await ctx.logger("agent.react(openai_agents): failed to build tool", {"type": t_type, "error": str(ex)}, node_id=node_id)

        # Final summary (avoid logging raw tool objects)
        await ctx.logger(
            f"agent.react(openai_agents): tools prepared\n Tools: {len(tools)}\n Toolkits: {toolkit_hints}\n Tool slugs: {tool_slugs}",
            {"num_tools": len(tools), "toolkits": toolkit_hints, "tool_slugs": tool_slugs},
            node_id=node_id,
        )

        # Create and run the OpenAI Agent with assembled tools
        try:
            from agents import Agent, Runner  # type: ignore
        except Exception as ex:
            raise ValueError(f"OpenAI Agents SDK not available: {ex}")

        def _choose_agents_model(name: Optional[str]) -> str:
            candidate = (name or "").strip() or "gpt-4o-mini"
            if candidate.lower().startswith("gpt-5"):
                return "gpt-4o-mini"
            return candidate

        agent = Agent(
            name="Agent",
            instructions=str(system),
            model=_choose_agents_model(s.get("model")),
            tools=tools,
        )

        try:
            result = await Runner.run(starting_agent=agent, input=str(rendered_prompt))
        except Exception as ex:
            await ctx.logger("agent.react(openai_agents): run error", {"error": str(ex)}, node_id=node_id)
            raise

        final_text = getattr(result, "final_output", None)
        if not isinstance(final_text, str):
            try:
                final_text = json.dumps(final_text, ensure_ascii=False)
            except Exception:
                final_text = str(final_text)

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
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system + "\nUse tools when needed. Reply with ReAct format."})
        messages.append({"role": "user", "content": str(prompt)})
        try:
            for step in range(1, max_steps + 1):
                completion = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                )
                msg = completion.choices[0].message.content or ""
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
                    result = await run_block(block_type, tool_run_input, ctx)
                    obs = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
                    messages.append({"role": "user", "content": f"Observation: {obs}"})
                    continue
                messages.append({"role": "user", "content": "Please provide Final Answer."})
            return AgentReactOutput(final="Failed to reach a final answer within max_steps.", trace=[]).model_dump()
        finally:
            await client.close() 