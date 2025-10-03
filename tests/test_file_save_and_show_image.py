from __future__ import annotations

import base64
from typing import Dict, Any

import pytest
import httpx


def _graph_file_save_inline(node_id: str, path: str, content_b64: str, content_type: str = "image/png") -> Dict[str, Any]:
    return {
        "nodes": [
            {"id": node_id, "type": "file.save", "settings": {"path": path, "content": content_b64, "content_type": content_type}},
            {"id": "show", "type": "show.image", "settings": {"title": "Preview"}},
        ],
        "edges": [
            {"id": "e1", "from": node_id, "to": "show"},
        ],
    }


def _graph_file_copy_via_ref(path_src: str, path_dst: str) -> Dict[str, Any]:
    return {
        "nodes": [
            {"id": "fs1", "type": "file.save", "settings": {"path": path_src, "content": "RAW_WILL_BE_REPLACED", "content_type": "image/png"}},
            {"id": "fs2", "type": "file.save", "settings": {"path": path_dst}},
            {"id": "show", "type": "show.image", "settings": {}},
        ],
        "edges": [
            {"id": "e1", "from": "fs1", "to": "fs2"},
            {"id": "e2", "from": "fs2", "to": "show"},
        ],
    }


def _poll_run(client, run_id: int, timeout_s: float = 3.0):
    import time

    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] in ("succeeded", "failed"):
            return last
        time.sleep(0.02)
    raise AssertionError("Run did not finish in time")


class MockSupabaseStorage:
    def __init__(self):
        self.bucket = "test-bucket"
        self.uploads: Dict[str, bytes] = {}

    def upload_bytes(self, path: str, data: bytes, *, content_type: str = "application/octet-stream", upsert: bool = True) -> str:
        self.uploads[path] = bytes(data)
        return f"supabase://{self.bucket}/{path}"

    def create_signed_url(self, path: str, *, expires_in: int | None = None) -> str:
        return f"https://example.com/signed/{path}?ttl={expires_in or 0}"

    def public_url(self, path: str) -> str:
        return f"https://public.example.com/{path}"


@pytest.fixture(autouse=True)
def _mock_supabase_and_http(monkeypatch):
    # Patch SupabaseStorage to our mock in both the module and the executor import binding
    import app.services.supabase_storage as ss
    import app.engine.executor as ex

    mock_storage = MockSupabaseStorage()
    monkeypatch.setattr(ss, "SupabaseStorage", lambda *a, **k: mock_storage)
    monkeypatch.setattr(ex, "SupabaseStorage", lambda *a, **k: mock_storage)

    # Patch HTTP client to serve bytes for our signed URLs
    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/signed/" in url:
            # Extract the path component after /signed/
            # URL format: https://example.com/signed/{path}?ttl=...
            try:
                after = url.split("/signed/")[1]
                path_only = after.split("?")[0]
                data = mock_storage.uploads.get(path_only, b"")
                return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=data)
            except Exception:
                return httpx.Response(404)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    import app.services.http as http_svc
    monkeypatch.setattr(
        http_svc,
        "create_http_client",
        lambda: httpx.AsyncClient(transport=transport),
    )

    yield


def test_file_save_inline_and_show_image(client):
    # Tiny 1x1 transparent PNG
    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9W3c6kQAAAAASUVORK5CYII="
    )
    b64_data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    graph = _graph_file_save_inline("fs", "images/test.png", b64_data_url, "image/png")
    r = client.post("/workflows", json={"name": "FS", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "succeeded"
    out_fs = run["outputs_json"]["fs"]
    assert "files" in out_fs and isinstance(out_fs["files"], list) and out_fs["files"]
    file0 = out_fs["files"][0]
    assert file0["storage"] == "supabase"
    assert file0["bucket"] == "test-bucket"
    assert file0["path"] == "images/test.png"
    assert file0.get("signed_url")

    out_show = run["outputs_json"]["show"]
    assert "images" in out_show and isinstance(out_show["images"], list)
    assert out_show["images"][0]["path"] == "images/test.png"


def test_file_save_from_upstream_ref_copy(client):
    # Prepare inline source content
    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9W3c6kQAAAAASUVORK5CYII="
    )
    b64_data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    graph = _graph_file_copy_via_ref("images/src.png", "images/dst.png")
    # Fill in the RAW_WILL_BE_REPLACED using a post-processing to keep function reusable
    for n in graph["nodes"]:
        if n["id"] == "fs1":
            n["settings"]["content"] = b64_data_url

    r = client.post("/workflows", json={"name": "FS-REF", "graph": graph})
    assert r.status_code == 200
    wf_id = r.json()["id"]

    r = client.post(f"/workflows/{wf_id}/run", json={})
    assert r.status_code == 200
    run_id = r.json()["id"]

    run = _poll_run(client, run_id)
    assert run["status"] == "succeeded"
    out_fs2 = run["outputs_json"]["fs2"]
    assert "files" in out_fs2 and out_fs2["files"][0]["path"] == "images/dst.png"
    out_show = run["outputs_json"]["show"]
    assert out_show["images"][0]["path"] == "images/dst.png"
