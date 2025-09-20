from __future__ import annotations

import time
from typing import Dict


def _simple_graph() -> Dict:
    return {
        "nodes": [
            {"id": "n1", "type": "start", "settings": {"payload": {"hello": "world"}}},
        ],
        "edges": [],
    }


def test_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_blocks(client):
    r = client.get("/blocks")
    assert r.status_code == 200
    blocks = r.json()["blocks"]
    # Expect std blocks to be registered
    for expected in ["start", "http.request", "gcs.write", "llm.simple", "transform.uppercase", "math.add", "json.get"]:
        assert expected in blocks


def test_workflow_lifecycle_and_run(client):
    slug = f"hello-webhook-{int(time.time()*1000)}"
    # Create
    r = client.post(
        "/workflows",
        json={
            "name": "Hello World",
            "webhook_slug": slug,
            "graph": _simple_graph(),
        },
    )
    assert r.status_code == 200
    wf_id = r.json()["id"]
    assert isinstance(wf_id, int)

    # Fetch
    r = client.get(f"/workflows/{wf_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Hello World"
    assert body["graph"]["nodes"][0]["type"] == "start"

    # Validate graph
    r = client.post("/validate-graph", json={"graph": _simple_graph()})
    assert r.status_code == 200
    assert r.json()["valid"] is True

    # Start a manual run
    r = client.post(f"/workflows/{wf_id}/run", json={"start_input": {"foo": "bar"}})
    assert r.status_code == 200
    run_id = r.json()["id"]

    # Poll run until finished (should be quick for single start node)
    for _ in range(50):
        rr = client.get(f"/runs/{run_id}")
        assert rr.status_code == 200
        status = rr.json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Run did not finish in time")

    rr_body = rr.json()
    assert rr_body["status"] == "succeeded"
    assert "outputs_json" in rr_body
    outputs = rr_body["outputs_json"]
    assert outputs["n1"]["data"] == {"hello": "world"}

    # Logs should exist
    r = client.get(f"/runs/{run_id}/logs")
    assert r.status_code == 200
    logs = r.json()
    assert isinstance(logs, list)
    assert any("Starting node n1" in (log.get("message") or "") for log in logs)


def test_webhook_trigger(client):
    # Create another workflow to test webhook
    slug = f"hook-{int(time.time()*1000)}"
    r = client.post(
        "/workflows",
        json={
            "name": "HookFlow",
            "webhook_slug": slug,
            "graph": _simple_graph(),
        },
    )
    assert r.status_code == 200
    wf_id = r.json()["id"]

    # Trigger via webhook
    r = client.post(f"/hooks/{slug}", json={"payload": {"from": "hook"}})
    assert r.status_code == 200
    run_id = r.json()["id"]
    assert isinstance(run_id, int)

    # Poll
    for _ in range(50):
        rr = client.get(f"/runs/{run_id}")
        assert rr.status_code == 200
        status = rr.json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("Run did not finish in time")

    rr_body = rr.json()
    assert rr_body["status"] in ("succeeded", "failed") 