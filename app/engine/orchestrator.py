from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import BackgroundTasks
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Run, Workflow
from ..db.session import SessionFactory
from .executor import execute_run


async def create_and_start_run(
    workflow_id: int,
    *,
    trigger_type: str = "manual",
    trigger_payload: Optional[Dict[str, Any]] = None,
    background_tasks: BackgroundTasks,
    user_id: Optional[str] = None,
) -> int:
    async with SessionFactory() as session:  # type: AsyncSession
        wf = await _get_workflow(session, workflow_id)
        if wf is None:
            raise ValueError("Workflow not found")
        run_id = await _insert_run(session, workflow_id, trigger_type, trigger_payload, user_id or getattr(wf, 'user_id', None))
        await session.commit()

    background_tasks.add_task(execute_run, run_id, SessionFactory, None)
    return run_id


async def _get_workflow(session: AsyncSession, workflow_id: int) -> Workflow | None:
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _insert_run(session: AsyncSession, workflow_id: int, trigger_type: str, trigger_payload: Optional[Dict[str, Any]], user_id: Optional[str]) -> int:
    stmt = insert(Run).values(workflow_id=workflow_id, trigger_type=trigger_type, trigger_payload_json=trigger_payload or {}, user_id=user_id)
    result = await session.execute(stmt)
    run_id = result.inserted_primary_key[0]
    return int(run_id)
