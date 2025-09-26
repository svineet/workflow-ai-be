from __future__ import annotations

from typing import Optional

try:
    from composio import Composio  # type: ignore
except Exception:  # pragma: no cover - composio optional in some envs
    Composio = None  # type: ignore

from ..server.settings import settings


def get_composio_client() -> Optional[object]:
    if Composio is None:
        return None
    if not settings.COMPOSIO_API_KEY:
        return None
    return Composio(api_key=settings.COMPOSIO_API_KEY) 