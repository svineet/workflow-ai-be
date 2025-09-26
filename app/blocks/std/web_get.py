from __future__ import annotations

from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class WebGetSettings(BaseModel):
    method: str = Field("GET", description="HTTP method (default: GET)")
    url: str = Field(..., description="Request URL (supports {{ }} substitutions)")
    headers: Optional[Dict[str, str]] = Field(default=None, description="HTTP headers")
    body: Optional[Any] = Field(default=None, description="JSON body or raw content (supports {{ }} if string)")
    follow_redirects: bool = Field(default=True, description="Follow HTTP redirects")
    timeout_seconds: float = Field(default=30.0, ge=0, description="Request timeout in seconds")
    response_mode: Literal["auto", "json", "text", "bytes"] = Field(
        default="auto",
        description="How to parse the response body: auto-detect, force json, force text, or raw bytes",
    )


class WebGetOutput(BaseModel):
    status: int
    headers: Dict[str, Any]
    data: Any
    data_text: Optional[str] = None
    data_json: Optional[Any] = None
    response_mode: Literal["json", "text", "bytes"]


@register("web.get")
class WebGetBlock(Block):
    type_name = "web.get"
    summary = "HTTP GET/Request with parsed outputs: status, headers, data, data_text, data_json"
    settings_model = WebGetSettings
    output_model = WebGetOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        method = (s.get("method") or "GET").upper()
        url_raw = s.get("url")
        if not url_raw:
            raise ValueError("web.get requires 'url'")
        headers = s.get("headers") or {}
        body = s.get("body")
        follow_redirects = bool(s.get("follow_redirects", True))
        timeout_seconds = float(s.get("timeout_seconds", 30.0))
        desired_mode = s.get("response_mode", "auto")

        url = self.render_expression(
            str(url_raw),
            upstream=input.get("upstream") or {},
            extra={"settings": s, "trigger": input.get("trigger") or {}},
        )
        if isinstance(body, str):
            body = self.render_expression(
                body,
                upstream=input.get("upstream") or {},
                extra={"settings": s, "trigger": input.get("trigger") or {}},
            )

        node_id = input.get("node_id")
        # Log request details (with safe body preview)
        try:
            preview = body if isinstance(body, (dict, list)) else (str(body)[:500] if body is not None else None)
        except Exception:
            preview = "<unserializable>"
        await ctx.logger(
            f"web.get: sending {method} {url}",
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body_preview": preview,
                "follow_redirects": follow_redirects,
                "timeout_seconds": timeout_seconds,
                "response_mode": desired_mode,
            },
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

        # Parse response according to mode
        chosen_mode: Literal["json", "text", "bytes"]
        data: Any = None
        data_text: Optional[str] = None
        data_json: Optional[Any] = None

        if desired_mode == "json":
            try:
                data_json = resp.json()
                data = data_json
                chosen_mode = "json"
            except Exception:
                # Fallback to text then bytes
                try:
                    buf = await resp.aread()
                except Exception:
                    buf = b""
                try:
                    data_text = buf.decode("utf-8")
                    data = data_text
                    chosen_mode = "text"
                except Exception:
                    data = buf
                    chosen_mode = "bytes"
        elif desired_mode == "text":
            try:
                buf = await resp.aread()
            except Exception:
                buf = b""
            try:
                data_text = buf.decode("utf-8")
                data = data_text
                chosen_mode = "text"
            except Exception:
                # Fallback to json or bytes
                try:
                    data_json = resp.json()
                    data = data_json
                    chosen_mode = "json"
                except Exception:
                    data = buf
                    chosen_mode = "bytes"
        elif desired_mode == "bytes":
            try:
                buf = await resp.aread()
            except Exception:
                buf = b""
            data = buf
            chosen_mode = "bytes"
        else:  # auto
            # Try JSON first
            try:
                data_json = resp.json()
                data = data_json
                chosen_mode = "json"
            except Exception:
                # Try text
                try:
                    buf = await resp.aread()
                except Exception:
                    buf = b""
                try:
                    data_text = buf.decode("utf-8")
                    data = data_text
                    chosen_mode = "text"
                except Exception:
                    data = buf
                    chosen_mode = "bytes"

        # Log response details (with safe body preview)
        try:
            data_preview = data if isinstance(data, (dict, list)) else (str(data)[:1000])
        except Exception:
            data_preview = "<unserializable>"
        await ctx.logger(
            f"web.get: received {resp.status_code}",
            {
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "data_preview": data_preview,
                "response_mode": chosen_mode,
            },
            node_id=node_id,
        )

        return WebGetOutput(
            status=resp.status_code,
            headers=dict(resp.headers),
            data=data,
            data_text=data_text,
            data_json=data_json,
            response_mode=chosen_mode,
        ).model_dump() 