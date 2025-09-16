from __future__ import annotations

from typing import Any, Dict

from ..registry import register
from ..base import RunContext


@register("http.request")
async def http_request_block(input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
    params: Dict[str, Any] = input.get("params") or {}
    method = (params.get("method") or "GET").upper()
    url = params.get("url")
    if not url:
        raise ValueError("http.request requires 'url'")
    headers = params.get("headers") or {}
    body = params.get("body")

    resp = await ctx.http.request(method, url, headers=headers, json=body if isinstance(body, (dict, list)) else None, content=None if isinstance(body, (dict, list, type(None))) else str(body).encode("utf-8"))

    data: Any
    try:
        data = resp.json()
    except Exception:
        data = await resp.aread()
        try:
            data = data.decode("utf-8")
        except Exception:
            pass

    return {
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "data": data,
    }
