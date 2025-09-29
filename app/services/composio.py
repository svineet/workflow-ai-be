from __future__ import annotations

from typing import Optional

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