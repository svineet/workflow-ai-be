from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class HttpRequestSettings(BaseModel):
    method: str = Field("GET", description="HTTP method")
    url: str = Field(..., description="Request URL (supports {{ }} substitutions)")
    headers: Optional[Dict[str, str]] = Field(default=None, description="HTTP headers")
    body: Optional[Any] = Field(default=None, description="JSON body or raw content (supports {{ }} if string)")
    follow_redirects: bool = Field(default=True, description="Follow HTTP redirects")
    timeout_seconds: float = Field(default=30.0, ge=0, description="Request timeout in seconds")


class HttpRequestOutput(BaseModel):
    status: int
    headers: Dict[str, Any]
    data: Any


@register("http.request")
class HttpRequestBlock(Block):
    type_name = "http.request"
    summary = "Perform an HTTP request and return status, headers, data"
    settings_model = HttpRequestSettings
    output_model = HttpRequestOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        method = (s.get("method") or "GET").upper()
        url_raw = s.get("url")
        if not url_raw:
            raise ValueError("http.request requires 'url'")
        headers = s.get("headers") or {}
        body = s.get("body")
        follow_redirects = bool(s.get("follow_redirects", True))
        timeout_seconds = float(s.get("timeout_seconds", 30.0))

        url = self.render_expression(str(url_raw), upstream=input.get("upstream") or {}, extra={"settings": s, "trigger": input.get("trigger") or {}})
        if isinstance(body, str):
            body = self.render_expression(body, upstream=input.get("upstream") or {}, extra={"settings": s, "trigger": input.get("trigger") or {}})

        node_id = input.get("node_id")
        # Log request details (with safe body preview)
        try:
            preview = body if isinstance(body, (dict, list)) else (str(body)[:500] if body is not None else None)
        except Exception:
            preview = "<unserializable>"
        await ctx.logger(
            f"http.request: sending {method} {url}",
            {"method": method, "url": url, "headers": headers, "body_preview": preview, "follow_redirects": follow_redirects, "timeout_seconds": timeout_seconds},
            node_id=node_id,
        )

        resp = await ctx.http.request(
            method,
            url,
            headers=headers,
            json=body if isinstance(body, (dict, list)) else None,
            content=None if isinstance(body, (dict, list, type(None))) else str(body).encode("utf-8"),
            follow_redirects=follow_redirects,
            timeout=timeout_seconds,
        )

        data: Any
        try:
            data = resp.json()
        except Exception:
            buf = await resp.aread()
            try:
                data = buf.decode("utf-8")
            except Exception:
                data = buf

        # Log response details (with safe body preview)
        try:
            data_preview = data if isinstance(data, (dict, list)) else (str(data)[:1000])
        except Exception:
            data_preview = "<unserializable>"
        await ctx.logger(
            f"http.request: received {resp.status_code}",
            {"status": resp.status_code, "headers": dict(resp.headers), "data_preview": data_preview},
            node_id=node_id,
        )

        return HttpRequestOutput(status=resp.status_code, headers=dict(resp.headers), data=data).model_dump()
