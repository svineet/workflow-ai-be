from __future__ import annotations

import os
import time

import pytest

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv might not be installed in some envs
    load_dotenv = None  # type: ignore


@pytest.mark.slow
def test_agent_with_openai_live(client):  # uses session client/DB, but sets OpenAI key dynamically
    # Load OPENAI_API_KEY from .env.dev if available
    if load_dotenv is not None:
        load_dotenv(".env.dev")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set; skipping live OpenAI test")

    # Patch the running settings singleton so blocks see the key
    from app.server.settings import settings

    settings.OPENAI_API_KEY = api_key

    # Create a simple agent workflow; keep temperature low for determinism and small tokens
    graph = {
        "nodes": [
            {
                "id": "agent",
                "type": "agent.react",
                "settings": {
                    "system": "You are a math assistant. Use the calculator tool when needed.",
                    "messages": [{"role": "user", "content": "What is 2 + 2?"}],
                    "model": "gpt-4o-mini",
                    "temperature": 0.0,
                    "max_steps": 3,
                    "tools": [
                        {"name": "calculator", "type": "tool.calculator", "settings": {}}
                    ],
                },
            },
        ],
        "edges": [],
    }

    r = client.post("/workflows", json={"name": "AgentCalcLive", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    # Poll for completion with a modest timeout
    deadline = time.time() + 30.0
    last = None
    while time.time() < deadline:
        rr = client.get(f"/runs/{run_id}")
        assert rr.status_code == 200
        last = rr.json()
        if last["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.25)

    assert last and last["status"] == "succeeded"
    final_text = str(last["outputs_json"]["agent"]["final"]).lower()
    assert "4" in final_text 