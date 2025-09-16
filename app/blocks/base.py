from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Protocol

import httpx

from ..services.gcs import GCSWriter


@dataclass
class RunContext:
    gcs: GCSWriter
    http: httpx.AsyncClient
    logger: Callable[[str, Dict[str, Any] | None, str | None], Awaitable[None]]


class Block(Protocol):
    async def __call__(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]: ...
