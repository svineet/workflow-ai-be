from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext
from ...server.settings import settings
from ...services.composio import get_composio_client


class ComposioToolSettings(BaseModel):
    toolkit: str = Field(..., description="Toolkit name, e.g., GMAIL")
    tool_slug: str = Field(..., description="Tool slug, e.g., GMAIL_SEND_EMAIL")
    use_account: Optional[str] = Field(default=None, description="Specific connected_account_id to use; if omitted, pick most recent active")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool (templated)")
    timeout_seconds: Optional[float] = Field(default=None, ge=1.0, description="Optional execution timeout; defaults to 60s")


class ComposioToolOutput(BaseModel):
    provider: str
    account_id: str
    result: Any


@register("tool.composio")
class ComposioToolBlock(Block):
    type_name = "tool.composio"
    summary = "Execute a Composio tool using a connected account"
    settings_model = ComposioToolSettings
    output_model = ComposioToolOutput
    tool_compatible = True

    @classmethod
    def extras(cls) -> Dict[str, Any]:
        return {"toolCompatible": True}

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        toolkit = s.get("toolkit")
        tool_slug = s.get("tool_slug")
        use_account = s.get("use_account")
        args_raw = s.get("args") or {}
        timeout_seconds = float(s.get("timeout_seconds") or 60.0)

        if not settings.COMPOSIO_API_KEY:
            raise ValueError("COMPOSIO_API_KEY is required for tool.composio")

        upstream = input.get("upstream") or {}
        extra_ctx = {"settings": s, "trigger": input.get("trigger") or {}, "nodes": upstream}

        def _render_map(obj: Any) -> Any:
            if isinstance(obj, str):
                return self.render_expression(obj, upstream=upstream, extra=extra_ctx)
            if isinstance(obj, dict):
                return {k: _render_map(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_render_map(v) for v in obj]
            return obj

        args = _render_map(args_raw)

        node_id = input.get("node_id")
        await ctx.logger(
            f"tool.composio: executing {tool_slug} on {toolkit}",
            {"toolkit": toolkit, "tool_slug": tool_slug, "use_account": use_account, "args_preview": str(args)[:500], "timeout_seconds": timeout_seconds},
            node_id=node_id,
        )

        # Resolve connected account id
        account_id = use_account
        if not account_id:
            # single-tenant lookup of most recent active account for toolkit
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession
            from ...db.models import ComposioAccount
            from ...db.session import SessionFactory

            async with SessionFactory() as session:  # type: AsyncSession
                # Prefer user_id from RunContext if available; fallback system-user
                current_user_id = getattr(ctx, "user_id", None) or "system-user"
                stmt = (
                    select(ComposioAccount)
                    .where(ComposioAccount.user_id == current_user_id, ComposioAccount.toolkit == toolkit)
                    .order_by(ComposioAccount.created_at.desc())
                )
                res = await session.execute(stmt)
                row = res.scalars().first()
                account_id = row.connected_account_id if row is not None else None

        if not account_id:
            await ctx.logger(
                f"tool.composio: No connected account found for toolkit {toolkit}. Authorize via Integrations.",
                {"toolkit": toolkit, "error": "No connected account"},
                node_id=input.get("node_id"),
            )
            raise ValueError(f"No connected account found for toolkit {toolkit}. Authorize via Integrations.")
        client = get_composio_client()
        resp: Any
        if client is None:
            await ctx.logger(
                f"tool.composio: Composio SDK not available; cannot execute {tool_slug}",
                {"toolkit": toolkit, "tool_slug": tool_slug, "args_preview": str(args)[:500], "error": "Composio SDK not available"},
                node_id=node_id,
            )
            resp = {"ok": True, "echo": {"tool_slug": tool_slug, "args": args}}
        else:
            try:
                resp = client.tools.execute(tool_slug, {
                    "userId": getattr(ctx, "user_id", None) or "system-user",
                    "connectedAccountId": account_id,
                    "arguments": args,
                    "timeout": timeout_seconds,
                })
            except Exception as ex:
                raise ValueError(f"Composio execute error: {ex}")

        await ctx.logger(
            f"tool.composio: executed {tool_slug}",
            {"result_preview": str(resp)[:1000], "account_id": account_id},
            node_id=node_id,
        )
        return ComposioToolOutput(provider=toolkit, account_id=account_id, result=resp).model_dump() 