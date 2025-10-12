from __future__ import annotations


def test_assistant_new_creates_workflow(client):
    prompt = "Create a simple workflow that shows hello"
    r = client.post("/assistant/new", json={"prompt": prompt})
    assert r.status_code == 200
    body = r.json()
    assert "id" in body and isinstance(body["id"], int)
    wf_id = body["id"]

    # Fetch the created workflow
    r2 = client.get(f"/workflows/{wf_id}")
    assert r2.status_code == 200
    wf = r2.json()
    assert wf["id"] == wf_id
    assert isinstance(wf.get("graph"), dict)
    assert isinstance(wf["graph"].get("nodes"), list)
    assert isinstance(wf["graph"].get("edges"), list)

    # Hitting the same prompt again should return cached flag
    r3 = client.post("/assistant/new", json={"prompt": prompt})
    assert r3.status_code == 200
    body2 = r3.json()
    assert body2["id"] == wf_id
    assert body2.get("cached") is True


