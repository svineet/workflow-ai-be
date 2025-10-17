import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.tool_builder import build_openai_tools, build_calculator_tool, build_http_tool
from app.blocks.base import RunContext

@pytest_asyncio.fixture
def mock_run_context():
    mock_logger = AsyncMock()
    return RunContext(gcs=None, http=None, logger=mock_logger)

@pytest.mark.asyncio
async def test_build_calculator_tool(mock_run_context):
    agent_input = {"node_id": "agent1"}
    tool = build_calculator_tool(agent_input, mock_run_context)
    
    assert tool.name == "calculator"
    assert "expression" in tool.params_json_schema["properties"]

@pytest.mark.asyncio
async def test_build_http_tool(mock_run_context):
    agent_input = {"node_id": "agent1"}
    tool = build_http_tool(agent_input, mock_run_context)
    
    assert tool.name == "http_request"
    assert "url" in tool.params_json_schema["required"]
    assert "body" in tool.params_json_schema["properties"]
    assert tool.params_json_schema["properties"]["headers"]["type"] == "string"
    assert tool.params_json_schema["properties"]["body"]["type"] == ["string", "null"]

@pytest.mark.asyncio
async def test_build_openai_tools(mock_run_context):
    tool_nodes = [
        {"type": "tool.calculator"},
        {"type": "tool.http_request"},
        {"type": "tool.websearch"},
        {"type": "tool.code_interpreter"},
        {"type": "tool.unsupported"},
    ]
    agent_input = {"node_id": "agent1"}

    tools = await build_openai_tools(tool_nodes, agent_input, mock_run_context)

    assert len(tools) == 4
    tool_names = [t.name for t in tools]
    assert "calculator" in tool_names
    assert "http_request" in tool_names
    assert "web-search" in tool_names # Name is defined by the SDK
    assert "code-interpreter" in tool_names
    
    # Check if logger was called for the unsupported tool
    mock_run_context.logger.assert_called_with(
        "tool_builder: no builder found for tool type",
        {"type": "tool.unsupported"},
        node_id="agent1"
    )

@pytest.mark.asyncio
async def test_http_tool_on_invoke(monkeypatch):
    mock_run_block = AsyncMock(return_value={"status": 200, "data": "ok"})
    monkeypatch.setattr("app.services.tool_builder.run_block", mock_run_block)

    mock_logger = AsyncMock()
    mock_ctx = RunContext(gcs=None, http=None, logger=mock_logger)
    agent_input = {"node_id": "agent1", "upstream": {}, "trigger": {}}
    
    http_tool = build_http_tool(agent_input, mock_ctx)
    
    # Simulate agent invoking the tool
    args = '{"method": "GET", "url": "https://example.com"}'
    result_json = await http_tool.on_invoke_tool(None, args)
    
    mock_run_block.assert_awaited_once()
    call_args = mock_run_block.call_args
    assert call_args[0][0] == "tool.http_request"
    assert call_args[0][1]["settings"]["url"] == "https://example.com"
    
    import json
    result = json.loads(result_json)
    assert result["status"] == 200
