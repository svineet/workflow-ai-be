from __future__ import annotations

from typing import Any, Dict

from ..registry import register
from ..base import RunContext


@register("gcs.write")
async def gcs_write_block(input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
    params: Dict[str, Any] = input.get("params") or {}
    path = params.get("path")
    if not path:
        raise ValueError("gcs.write requires 'path'")
    content = params.get("content")
    as_json = bool(params.get("as_json"))

    if as_json:
        import json

        data_bytes = json.dumps(content).encode("utf-8")
        content_type = "application/json"
    else:
        if isinstance(content, (dict, list)):
            import json

            data_bytes = json.dumps(content).encode("utf-8")
            content_type = "application/json"
        elif isinstance(content, (bytes, bytearray)):
            data_bytes = bytes(content)
            content_type = "application/octet-stream"
        else:
            data_bytes = (str(content) if content is not None else "").encode("utf-8")
            content_type = "text/plain; charset=utf-8"

    uri = ctx.gcs.write_bytes(path, data_bytes, content_type=content_type)
    return {"gcs_uri": uri, "size": len(data_bytes)}
