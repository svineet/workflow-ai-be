from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field
from openai import AsyncOpenAI

from ..registry import register
from ..base import Block, RunContext
from ...server.settings import settings


class AgentToolSpec(BaseModel):
    name: str = Field(..., description="Tool name exposed to the LLM")
    type: str = Field(..., description="Block type to invoke as the tool (e.g., 'tool.calculator')")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Base settings for the tool block")


class AgentReactSettings(BaseModel):
    system: Optional[str] = Field(default="You are a helpful assistant. Use tools when needed.")
    # Prefer a single prompt field
    prompt: Optional[str] = Field(default=None, description="Single user prompt (supports Jinja)")
    tools: Optional[List[AgentToolSpec]] = Field(default=None, description="List of tool definitions for the agent")
    model: Optional[str] = Field(default="gpt-4o-mini", description="OpenAI model")
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
    summary = "ReAct-style agent that loops until final answer; supports tool calls"
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
        model = s.get("model") or "gpt-5"
        temperature = float(s.get("temperature", 1))
        max_steps = int(s.get("max_steps", 8))
        system = s.get("system") or "You are a helpful assistant. Use tools when needed."
        prompt_single: Optional[str] = s.get("prompt")
        tools_spec: List[Dict[str, Any]] = list(s.get("tools") or [])

        node_id = input.get("node_id")
        await ctx.logger(
            f"agent.react: starting [{model}]",
            {"model": model, "temperature": temperature, "num_tools": len(tools_spec)},
            node_id=node_id,
        )

        # Render system and inputs with upstream/settings/trigger context
        upstream_ctx = input.get("upstream") or {}
        # Make node ids directly point to their data payloads, e.g., {{ start.query }}
        flat_nodes_ctx: Dict[str, Any] = {}
        try:
            for k, v in (upstream_ctx or {}).items():
                if isinstance(v, dict) and "data" in v:
                    flat_nodes_ctx[k] = v.get("data")
                else:
                    flat_nodes_ctx[k] = v
        except Exception:
            flat_nodes_ctx = {}
        extra_ctx = {"settings": s, "trigger": input.get("trigger") or {}, **flat_nodes_ctx, "upstream": upstream_ctx}
        try:
            system_rendered = self.render_expression(system, upstream=upstream_ctx, extra=extra_ctx) if isinstance(system, str) else str(system)
        except Exception:
            system_rendered = system if isinstance(system, str) else ""

        rendered_messages: List[Dict[str, Any]] = []
        if prompt_single is None or not str(prompt_single).strip():
            raise ValueError("agent.react requires 'prompt'")
        try:
            content = self.render_expression(str(prompt_single), upstream=upstream_ctx, extra=extra_ctx)
        except Exception:
            content = str(prompt_single)
        rendered_messages.append({"role": "user", "content": content})

        async def call_tool(tool_name: str, tool_input: Any) -> Any:
            spec = next((t for t in tools_spec if t.get("name") == tool_name), None)
            if not spec:
                raise ValueError(f"Unknown tool: {tool_name}")
            block_type = spec.get("type")
            base_settings = spec.get("settings") or {}
            merged_settings = dict(base_settings)
            if isinstance(tool_input, dict):
                merged_settings.update(tool_input)
            else:
                if "expression" in base_settings or spec.get("type", "").endswith("calculator"):
                    merged_settings["expression"] = str(tool_input)
                else:
                    merged_settings["input"] = tool_input

            tool_run_input: Dict[str, Any] = {
                "settings": merged_settings,
                "upstream": upstream_ctx,
                "trigger": input.get("trigger") or {},
                "node_id": f"{node_id}::tool::{tool_name}",
            }
            await ctx.logger(
                f"agent.react: invoking tool {tool_name} ({block_type})",
                {"tool_name": tool_name, "settings": merged_settings},
                node_id=node_id,
            )
            result = await self._run_block(block_type, tool_run_input, ctx)
            await ctx.logger(
                f"agent.react: tool {tool_name} returned",
                {"result_preview": str(result)[:200]},
                node_id=node_id,
            )
            return result

        tool_instructions = "\n".join((f"- {t.get('name')}: call with JSON input." for t in tools_spec)) or "(no tools available)"
        react_instructions = (
            "You may use tools. When using a tool, respond EXACTLY in this format:\n"
            "Action: <tool_name>\n"
            "Action Input: <JSON or plain text>\n"
            "If you have the final answer, respond with:\n"
            "Final Answer: <text>\n"
        )

        convo: List[Dict[str, Any]] = []
        if system_rendered:
            convo.append({"role": "system", "content": system_rendered + "\nAvailable tools:\n" + str(tool_instructions) + "\n" + react_instructions})
        convo.extend(rendered_messages)

        trace: List[Dict[str, Any]] = []

        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for agent.react execution")

        client = AsyncOpenAI(api_key=api_key)
        try:
            observation: Optional[str] = None
            for step in range(1, max_steps + 1):
                if observation is not None:
                    convo.append({"role": "user", "content": f"Observation: {observation}"})
                    observation = None

                completion = await client.chat.completions.create(
                    model=model,
                    messages=convo,
                    temperature=temperature,
                )
                msg = completion.choices[0].message.content or ""
                trace.append({"step": step, "assistant": msg})
                await ctx.logger(
                    f"agent.react: step {step}",
                    {"assistant_msg_preview": msg[:1000]},
                    node_id=node_id,
                )

                final_match = re.search(r"Final Answer:\s*(.*)", msg, re.IGNORECASE | re.DOTALL)
                if final_match:
                    final_text = final_match.group(1).strip()
                    return AgentReactOutput(final=final_text, trace=trace).model_dump()

                action_match = re.search(r"Action:\s*([^\n]+)\nAction Input:\s*(.*)", msg, re.IGNORECASE | re.DOTALL)
                if action_match:
                    tool_name = action_match.group(1).strip()
                    raw_input = action_match.group(2).strip()
                    try:
                        tool_input = json.loads(raw_input)
                    except Exception:
                        tool_input = raw_input

                    try:
                        result = await call_tool(tool_name, tool_input)
                        observation = json.dumps(result, ensure_ascii=False)
                    except Exception as ex:
                        observation = f"Tool {tool_name} error: {ex}"

                    convo.append({"role": "user", "content": f"Observation: {observation}"})
                    continue

                convo.append({"role": "user", "content": "Please provide Final Answer."})

            return AgentReactOutput(final="Failed to reach a final answer within max_steps.", trace=trace).model_dump()
        finally:
            await client.close()

    async def _run_block(self, type_name: str, input: Dict[str, Any], ctx: RunContext) -> Any:
        from ..registry import run_block
        return await run_block(type_name, input, ctx)  # type: ignore[return-value] 