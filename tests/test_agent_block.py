from __future__ import annotations

from typing import Dict, Any


def _graph_agent_calc() -> Dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "agent",
                "type": "agent.react",
                "settings": {
                    "system": "You are a math assistant. Use tools when needed.",
                    "messages": [{"role": "user", "content": "What is (12 + 7) * 3?"}],
                    "model": "gpt-5",
                    "temperature": 1,
                    "max_steps": 3,
                    "tools": [
                        {"name": "calculator", "type": "tool.calculator", "settings": {"expression": "(12+7)*3"}}
                    ],
                },
            },
        ],
        "edges": [],
    }


def test_agent_with_calculator_tool_offline(client):
    # With OPENAI_API_KEY empty (per conftest), agent falls back to calculator-only path
    graph = _graph_agent_calc()
    r = client.post("/workflows", json={"name": "AgentCalc", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    # Poll until completion
    import time
    deadline = time.time() + 3.0
    last = None
    while time.time() < deadline:
        rr = client.get(f"/runs/{run_id}")
        assert rr.status_code == 200
        last = rr.json()
        if last["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    assert last and last["status"] == "succeeded"
    # In fallback, final should be the computed value as string
    assert last["outputs_json"]["agent"]["final"] in ("57.0", "57") 