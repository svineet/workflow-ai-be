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
from ...services.tool_builder import build_openai_tools


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
        # Extract user_id from run to pass to Composio for user-scoped connections
        run_user_id = input.get("user_id")
        if not run_user_id:
            await ctx.logger(
                "agent.react: missing user_id; Composio tools will not be loaded",
                {"error": "missing_user_id"},
                node_id=node_id,
            )
        if (toolkit_hints or tool_slugs) and run_user_id:
            # Validate user has connected accounts before fetching tools
            from ...services.composio import get_user_composio_accounts, derive_toolkit_from_slug
            
            user_accounts_by_toolkit = await get_user_composio_accounts(run_user_id)
            
            composio_agents = get_composio_openai_agents_client()
            if composio_agents is None:
                raise ValueError("Composio OpenAI Agents provider is not available. Ensure composio-openai-agents is installed and COMPOSIO_API_KEY is set.")
            try:
                if toolkit_hints:
                    # Filter to toolkits that have connected accounts
                    valid_toolkits = [tk for tk in toolkit_hints if tk in user_accounts_by_toolkit]
                    missing_toolkits = [tk for tk in toolkit_hints if tk not in user_accounts_by_toolkit]
                    if missing_toolkits:
                        await ctx.logger(
                            f"agent.react: missing connected accounts for toolkits: {', '.join(missing_toolkits)}",
                            {"missing_toolkits": missing_toolkits, "user_id": run_user_id},
                            node_id=node_id,
                        )
                    if valid_toolkits:
                        for tk in valid_toolkits:
                            await ctx.logger(
                                f"agent.react: using {tk} account",
                                {"toolkit": tk, "account_id": user_accounts_by_toolkit[tk], "user_id": run_user_id},
                                node_id=node_id,
                            )
                        tk_tools = composio_agents.tools.get(user_id=run_user_id, toolkits=valid_toolkits)
                        if isinstance(tk_tools, list):
                            tools.extend(tk_tools)
                        await ctx.logger(
                            "agent.react(openai_agents): fetched tools by toolkits",
                            {"count": len(tk_tools) if isinstance(tk_tools, list) else 0, "toolkits": valid_toolkits},
                            node_id=node_id,
                        )
                    else:
                        await ctx.logger(
                            "agent.react: no valid connected accounts for requested toolkits",
                            {"requested": toolkit_hints, "user_id": run_user_id},
                            node_id=node_id,
                        )
                if tool_slugs:
                    # Derive toolkit from each slug and validate account availability
                    valid_slugs = []
                    for slug in tool_slugs:
                        slug_toolkit = derive_toolkit_from_slug(slug)
                        if slug_toolkit and slug_toolkit in user_accounts_by_toolkit:
                            valid_slugs.append(slug)
                            await ctx.logger(
                                f"agent.react: using {slug_toolkit} account for tool {slug}",
                                {"toolkit": slug_toolkit, "account_id": user_accounts_by_toolkit[slug_toolkit], "user_id": run_user_id},
                                node_id=node_id,
                            )
                        elif slug_toolkit:
                            await ctx.logger(
                                f"agent.react: missing account for tool {slug} (toolkit {slug_toolkit})",
                                {"slug": slug, "derived_toolkit": slug_toolkit, "user_id": run_user_id},
                                node_id=node_id,
                            )
                    if valid_slugs:
                        slug_tools = composio_agents.tools.get(user_id=run_user_id, tools=valid_slugs)
                        if isinstance(slug_tools, list):
                            tools.extend(slug_tools)
                        await ctx.logger(
                            "agent.react(openai_agents): fetched tools by slugs",
                            {"count": len(slug_tools) if isinstance(slug_tools, list) else 0, "slugs": valid_slugs},
                            node_id=node_id,
                        )
                if not tools and not (toolkit_hints or tool_slugs):
                    # Fallback: use env COMPOSIO_TOOLKITS if configured, but only if user has accounts
                    valid_env_toolkits = [tk for tk in settings.COMPOSIO_TOOLKITS if tk in user_accounts_by_toolkit]
                    if valid_env_toolkits:
                        env_tools = composio_agents.tools.get(user_id=run_user_id, toolkits=valid_env_toolkits)
                        if isinstance(env_tools, list):
                            tools.extend(env_tools)
                        await ctx.logger(
                            "agent.react(openai_agents): fetched tools from env toolkits",
                            {"count": len(env_tools) if isinstance(env_tools, list) else 0, "toolkits": valid_env_toolkits},
                            node_id=node_id,
                        )
                    else:
                        await ctx.logger(
                            "agent.react: no connected accounts for env toolkits",
                            {"env_toolkits": settings.COMPOSIO_TOOLKITS, "user_id": run_user_id},
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
            tools.extend(await build_openai_tools(non_composio_tools, input, ctx))

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

        # Log summary of agent completion
        await ctx.logger(
            "agent.react(openai_agents): completed",
            {"user_id": run_user_id or "none", "toolkits": toolkit_hints, "tool_slugs": tool_slugs},
            node_id=node_id,
        )

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