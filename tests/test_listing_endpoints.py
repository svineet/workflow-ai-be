from __future__ import annotations

import time
from typing import Any, Dict


def _graph_single(node_id: str, type_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nodes": [
            {"id": node_id, "type": type_name, "params": params},
        ],
        "edges": [],
    }


def _poll_run(client, run_id: int, timeout_s: float = 3.0):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.05)
    raise AssertionError("Run did not finish in time")


def test_list_workflows_and_runs_filters(client):
    # Create two simple workflows
    g1 = _graph_single("n1", "transform.uppercase", {"text": "x"})
    g2 = _graph_single("n2", "math.add", {"a": 1, "b": 1})

    r = client.post("/workflows", json={"name": "WF1", "graph": g1})
    assert r.status_code == 200
    wf1 = r.json()["id"]

    r = client.post("/workflows", json={"name": "WF2", "graph": g2})
    assert r.status_code == 200
    wf2 = r.json()["id"]

    # List workflows
    r = client.get("/workflows")
    assert r.status_code == 200
    workflows = r.json()
    ids = [w["id"] for w in workflows]
    assert wf1 in ids and wf2 in ids

    # Start runs for both
    r = client.post(f"/workflows/{wf1}/run", json={})
    assert r.status_code == 200
    run1 = r.json()["id"]

    r = client.post(f"/workflows/{wf2}/run", json={})
    assert r.status_code == 200
    run2 = r.json()["id"]

    # Wait to finish
    r1 = _poll_run(client, run1)
    r2 = _poll_run(client, run2)
    assert r1["status"] in ("succeeded", "failed")
    assert r2["status"] in ("succeeded", "failed")

    # List all runs
    r = client.get("/runs")
    assert r.status_code == 200
    runs = r.json()
    run_ids = [rr["id"] for rr in runs]
    assert run1 in run_ids and run2 in run_ids

    # Filter by workflow_id
    r = client.get(f"/runs?workflow_id={wf1}")
    assert r.status_code == 200
    filtered = r.json()
    assert all(rr["workflow_id"] == wf1 for rr in filtered)
    assert any(rr["id"] == run1 for rr in filtered)

    # Filter by status (succeeded expected for simple blocks)
    r = client.get("/runs", params={"status": "succeeded"})
    assert r.status_code == 200
    by_status = r.json()
    assert all(rr["status"] == "succeeded" for rr in by_status)

    # Invalid status -> 400
    r = client.get("/runs", params={"status": "not-a-status"})
    assert r.status_code == 400 