from __future__ import annotations

import time
from typing import Dict, Any


def _graph_single(node_id: str, type_name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nodes": [
            {"id": node_id, "type": type_name, "settings": settings},
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


def test_blocks_and_specs(client):
    # /blocks includes both function and executor types
    r = client.get("/blocks")
    assert r.status_code == 200
    names = set(r.json()["blocks"])
    for expected in [
        "start",
        "http.request",
        "gcs.write",
        "llm.simple",
        "transform.uppercase",
        "math.add",
        "json.get",
    ]:
        assert expected in names

    # /block-specs contains schemas for executor blocks
    r = client.get("/block-specs")
    assert r.status_code == 200
    specs = r.json()["blocks"]
    spec_by_type = {s["type"]: s for s in specs}
    uc = spec_by_type["transform.uppercase"]
    assert uc["kind"] == "executor"
    assert "settings_schema" in uc and "text" in uc["settings_schema"]["properties"]

    add = spec_by_type["math.add"]
    assert add["kind"] == "executor"
    assert set(add["settings_schema"]["properties"].keys()) >= {"a", "b"}

    jg = spec_by_type["json.get"]
    assert jg["kind"] == "executor"
    assert "path" in jg["settings_schema"]["properties"]


def test_run_uppercase_executor(client):
    # Create workflow with single uppercase node
    graph = _graph_single("u1", "transform.uppercase", {"text": "foo"})
    r = client.post("/workflows", json={"name": "UC", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["outputs_json"]["u1"]["text"] == "FOO"


def test_run_math_add_executor(client):
    graph = _graph_single("m1", "math.add", {"a": 1, "b": 2})
    r = client.post("/workflows", json={"name": "ADD", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["outputs_json"]["m1"]["result"] == 3


def test_run_json_get_executor(client):
    source = {"a": {"b": {"c": 42}}}
    graph = _graph_single("j1", "json.get", {"source": source, "path": ["a", "b", "c"]})
    r = client.post("/workflows", json={"name": "JG", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["outputs_json"]["j1"]["value"] == 42


def test_run_uppercase_executor_with_settings(client):
    graph = {
        "nodes": [
            {
                "id": "u1",
                "type": "transform.uppercase",
                "settings": {"text": " foo \n", "trim_whitespace": True},
            }
        ],
        "edges": [],
    }
    r = client.post("/workflows", json={"name": "UC2", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["outputs_json"]["u1"]["text"] == "FOO"


def test_jinja_templating_prompt_and_url(client):
    # start -> template -> uppercase
    graph = {
        "nodes": [
            {"id": "s", "type": "start", "settings": {"payload": {"name": "Alice"}}},
            {"id": "t", "type": "transform.template", "settings": {"template": "Hello {{ s.data.name }}", "values": {}}},
            {"id": "u", "type": "transform.uppercase", "settings": {"text": "{{ t.text }}"}},
        ],
        "edges": [
            {"id": "e1", "from": "s", "to": "t"},
            {"id": "e2", "from": "t", "to": "u"},
        ],
    }

    r = client.post("/workflows", json={"name": "JinjaFlow", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["outputs_json"]["t"]["text"] == "Hello Alice"
    assert run["outputs_json"]["u"]["text"] == "HELLO ALICE"


def test_run_unknown_block_fails(client):
    graph = _graph_single("x1", "does.not.exist", {})
    r = client.post("/workflows", json={"name": "BAD", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "failed" 