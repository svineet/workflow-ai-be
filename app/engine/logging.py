from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Log, Run


async def insert_log(session: AsyncSession, run_id: int, message: str, *, node_id: Optional[str] = None, level: str = "info", data: Optional[Dict[str, Any]] = None) -> None:
    # Derive user_id from run to denormalize for faster per-user queries
    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    user_id = getattr(run, "user_id", None) if run is not None else None
    stmt = insert(Log).values(run_id=run_id, user_id=user_id, node_id=node_id, level=level, message=message, data_json=data or {})
    await session.execute(stmt)
    # Commit immediately so streaming clients in a separate session can see the log
    await session.commit()
