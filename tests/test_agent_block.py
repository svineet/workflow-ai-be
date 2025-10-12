from __future__ import annotations

import os
from typing import Dict, Any
import pytest


def _graph_agent_calc() -> Dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "agent",
                "type": "agent.react",
                "settings": {
                    "system": "You are a math assistant. Use tools when needed.",
                    "prompt": "What is (12 + 7) * 3?",
                    "model": "gpt-5",
                    "temperature": 1,
                    "max_steps": 3,
                },
            },
            {"id": "calc", "type": "tool.calculator", "settings": {}},
        ],
        "edges": [
            {"id": "t1", "from": "agent", "to": "calc", "kind": "tool"}
        ],
    }


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="Agent requires OPENAI_API_KEY")
def test_agent_with_calculator_tool_offline(client):
    graph = _graph_agent_calc()
    r = client.post("/workflows", json={"name": "AgentCalc", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    # Poll until completion
    import time
    deadline = time.time() + 5.0
    last = None
    while time.time() < deadline:
        rr = client.get(f"/runs/{run_id}")
        assert rr.status_code == 200
        last = rr.json()
        if last["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    assert last and last["status"] == "succeeded"
    assert last["outputs_json"]["agent"]["final"] 