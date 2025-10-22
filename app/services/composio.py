from __future__ import annotations

from typing import Optional, Dict

try:
    from composio import Composio  # type: ignore
except Exception:  # pragma: no cover - composio optional in some envs
    Composio = None  # type: ignore

try:
    from composio_openai import OpenAIProvider  # type: ignore
except Exception:  # pragma: no cover - provider optional
    OpenAIProvider = None  # type: ignore

try:
    from composio_openai_agents import OpenAIAgentsProvider  # type: ignore
except Exception:  # pragma: no cover - provider optional
    OpenAIAgentsProvider = None  # type: ignore

from ..server.settings import settings


def get_composio_client() -> Optional[object]:
    if Composio is None:
        return None
    if not settings.COMPOSIO_API_KEY:
        return None
    return Composio(api_key=settings.COMPOSIO_API_KEY)


def get_composio_openai_client() -> Optional[object]:
    if Composio is None or OpenAIProvider is None:
        return None
    if not settings.COMPOSIO_API_KEY:
        return None
    try:
        provider = OpenAIProvider()
        return Composio(provider=provider, api_key=settings.COMPOSIO_API_KEY)
    except Exception:
        return None


def get_composio_openai_agents_client() -> Optional[object]:
    if Composio is None or OpenAIAgentsProvider is None:
        return None
    if not settings.COMPOSIO_API_KEY:
        return None
    try:
        provider = OpenAIAgentsProvider()
        return Composio(provider=provider, api_key=settings.COMPOSIO_API_KEY)
    except Exception:
        return None


async def get_user_composio_accounts(user_id: str) -> Dict[str, str]:
    """
    Fetch all ComposioAccounts for a user and return a dict mapping toolkit -> most_recent_connected_account_id.
    """
    from sqlalchemy import select
    from ..db.models import ComposioAccount
    from ..db.session import SessionFactory
    
    async with SessionFactory() as session:
        stmt = select(ComposioAccount).where(ComposioAccount.user_id == user_id).order_by(ComposioAccount.created_at.desc())
        res = await session.execute(stmt)
        rows = res.scalars().all()
        
    accounts_by_toolkit: Dict[str, str] = {}
    for row in rows:
        tk = row.toolkit
        if tk not in accounts_by_toolkit:
            accounts_by_toolkit[tk] = row.connected_account_id
    return accounts_by_toolkit


def derive_toolkit_from_slug(tool_slug: str) -> Optional[str]:
    """
    Derive toolkit from a tool slug, e.g., SLACK_SEND_MESSAGE -> SLACK.
    """
    try:
        return str(tool_slug).split("_", 1)[0].upper()
    except Exception:
        return None 