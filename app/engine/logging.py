from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Log


async def insert_log(session: AsyncSession, run_id: int, message: str, *, node_id: Optional[str] = None, level: str = "info", data: Optional[Dict[str, Any]] = None) -> None:
    stmt = insert(Log).values(run_id=run_id, node_id=node_id, level=level, message=message, data_json=data or {})
    await session.execute(stmt)
