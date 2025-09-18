from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class HttpRequestInput(BaseModel):
    method: str = Field("GET", description="HTTP method")
    url: str = Field(..., description="Request URL")
    headers: Optional[Dict[str, str]] = Field(default=None, description="HTTP headers")
    body: Optional[Any] = Field(default=None, description="JSON body or raw content")


class HttpRequestOutput(BaseModel):
    status: int
    headers: Dict[str, Any]
    data: Any


@register("http.request")
class HttpRequestBlock(Block):
    type_name = "http.request"
    summary = "Perform an HTTP request and return status, headers, data"
    input_model = HttpRequestInput
    output_model = HttpRequestOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        method = (self.params.get("method") or "GET").upper()
        url = self.params.get("url")
        if not url:
            raise ValueError("http.request requires 'url'")
        headers = self.params.get("headers") or {}
        body = self.params.get("body")

        resp = await ctx.http.request(
            method,
            url,
            headers=headers,
            json=body if isinstance(body, (dict, list)) else None,
            content=None if isinstance(body, (dict, list, type(None))) else str(body).encode("utf-8"),
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

        return HttpRequestOutput(status=resp.status_code, headers=dict(resp.headers), data=data).model_dump()
