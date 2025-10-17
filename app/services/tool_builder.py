from __future__ import annotations
import json
from typing import Any, Dict, List

from ..blocks.base import RunContext
from ..blocks.registry import run_block

try:
    from agents import FunctionTool, WebSearchTool, CodeInterpreterTool
except ImportError:
    FunctionTool = None
    WebSearchTool = None
    CodeInterpreterTool = None


def build_calculator_tool(agent_input: Dict[str, Any], ctx: RunContext) -> Any:
    node_id = agent_input.get("node_id")

    async def on_invoke(ctx_wrap, args_json: str) -> str:
        try:
            data = json.loads(args_json) if args_json else {}
        except Exception:
            data = {"expression": args_json}
        if not isinstance(data, dict):
            data = {"expression": str(data)}
        merged_settings = {"expression": data.get("expression")}
        tool_run_input: Dict[str, Any] = {
            "settings": merged_settings,
            "upstream": agent_input.get("upstream") or {},
            "trigger": agent_input.get("trigger") or {},
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

def build_http_tool(agent_input: Dict[str, Any], ctx: RunContext) -> Any:
    node_id = agent_input.get("node_id")
    
    async def on_invoke(ctx_wrap, args_json: str) -> str:
        try:
            settings_in = json.loads(args_json) if args_json else {}
        except Exception:
            settings_in = {}
        tool_run_input: Dict[str, Any] = {
            "settings": settings_in,
            "upstream": agent_input.get("upstream") or {},
            "trigger": agent_input.get("trigger") or {},
            "node_id": f"{node_id}::tool::http_request",
        }
        result = await run_block("tool.http_request", tool_run_input, ctx)
        return json.dumps(result, ensure_ascii=False)

    params = {
        "title": "http_request_args",
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                "description": "HTTP method"
            },
            "url": {"type": "string", "description": "Request URL"},
            "headers": {
                "type": "string",
                "description": "HTTP headers as a JSON string. E.g., '{\\\"Content-Type\\\": \\\"application/json\\\"}'"
            },
            "body": {
                "type": ["string", "null"],
                "description": "Request body as a string. For JSON, serialize it to a string first."
            },
            "timeout_seconds": {
                "type": "number",
                "minimum": 0,
                "description": "Optional timeout in seconds"
            },
        },
        "required": ["url"],
    }
    return FunctionTool(
        name="http_request",
        description="Perform an HTTP request and return status, headers, data",
        params_json_schema=params,
        on_invoke_tool=on_invoke,
    )

def build_websearch_tool(agent_input: Dict[str, Any], ctx: RunContext) -> Any:
    return WebSearchTool()

def build_code_interpreter_tool(agent_input: Dict[str, Any], ctx: RunContext) -> Any:
    return CodeInterpreterTool()


type_to_builder = {
    "tool.calculator": build_calculator_tool,
    "tool.http_request": build_http_tool,
    "tool.websearch": build_websearch_tool,
    "tool.code_interpreter": build_code_interpreter_tool,
}

async def build_openai_tools(
    tool_nodes: List[Dict[str, Any]], 
    agent_input: Dict[str, Any], 
    ctx: RunContext
) -> List[Any]:
    
    if FunctionTool is None:
        await ctx.logger("tool_builder: OpenAI Agents SDK not available, cannot build tools.")
        return []

    tools = []
    node_id = agent_input.get("node_id")

    for t in tool_nodes:
        t_type = str(t.get("type") or "")
        builder = type_to_builder.get(t_type)
        if builder is None:
            await ctx.logger("tool_builder: no builder found for tool type", {"type": t_type}, node_id=node_id)
            continue
        try:
            tool_obj = builder(agent_input, ctx)
            tools.append(tool_obj)
        except Exception as ex:
            await ctx.logger("tool_builder: failed to build tool", {"type": t_type, "error": str(ex)}, node_id=node_id)

    return tools
