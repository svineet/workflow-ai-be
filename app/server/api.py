from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import blocks  # noqa: F401 — ensure registry is populated
from ..blocks.registry import list_blocks, list_block_specs
from ..db.models import Log, Run, Workflow
from ..db.session import SessionFactory
from ..engine.graph import toposort
from ..schemas.graph import Graph
from ..schemas.run import RunCreate
from ..engine.orchestrator import create_and_start_run

router = APIRouter()


async def get_session() -> AsyncSession:
    async with SessionFactory() as session:
        yield session


class WorkflowCreate(BaseModel):
    name: str
    webhook_slug: Optional[str] = None
    graph: Graph


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    webhook_slug: Optional[str] = None
    graph: Optional[Graph] = None


@router.post("/workflows")
async def create_workflow(body: WorkflowCreate, session: AsyncSession = Depends(get_session)):
    stmt = insert(Workflow).values(
        name=body.name,
        webhook_slug=body.webhook_slug,
        graph_json=body.graph.model_dump(by_alias=True),
    )
    result = await session.execute(stmt)
    await session.commit()
    return {"id": int(result.inserted_primary_key[0])}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    result = await session.execute(stmt)
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {
        "id": wf.id,
        "name": wf.name,
        "webhook_slug": wf.webhook_slug,
        "graph": wf.graph_json,
        "created_at": wf.created_at.isoformat(),
    }


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: int, body: WorkflowUpdate, session: AsyncSession = Depends(get_session)):
    values: Dict[str, Any] = {}
    if body.name is not None:
        values["name"] = body.name
    if body.webhook_slug is not None:
        values["webhook_slug"] = body.webhook_slug
    if body.graph is not None:
        values["graph_json"] = body.graph.model_dump(by_alias=True)

    if not values:
        return {"updated": False}

    await session.execute(update(Workflow).where(Workflow.id == workflow_id).values(**values))
    await session.commit()
    return {"updated": True}


class ValidateGraphBody(BaseModel):
    graph: Graph


@router.post("/validate-graph")
async def validate_graph(body: ValidateGraphBody):
    _ = toposort(body.graph)
    return {"valid": True}


@router.post("/workflows/{workflow_id}/run")
async def start_run(workflow_id: int, body: RunCreate | None = None, background_tasks: BackgroundTasks = None):
    background_tasks = background_tasks or BackgroundTasks()
    run_id = await create_and_start_run(
        workflow_id,
        trigger_type="manual",
        trigger_payload=(body.start_input if body else None) or {},
        background_tasks=background_tasks,
    )
    return {"id": run_id}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Run).where(Run.id == run_id)
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "trigger_type": run.trigger_type,
        "outputs_json": run.outputs_json,
    }


@router.get("/runs/{run_id}/logs")
async def get_run_logs(run_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Log).where(Log.run_id == run_id).order_by(Log.ts.asc())
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": row.id,
            "run_id": row.run_id,
            "node_id": row.node_id,
            "ts": row.ts.isoformat(),
            "level": row.level,
            "message": row.message,
            "data": row.data_json,
        }
        for row in rows
    ]


class HookPayload(BaseModel):
    payload: Dict[str, Any]


@router.post("/hooks/{slug}")
async def webhook_trigger(slug: str, body: HookPayload, background_tasks: BackgroundTasks = None, session: AsyncSession = Depends(get_session)):
    background_tasks = background_tasks or BackgroundTasks()
    stmt = select(Workflow).where(Workflow.webhook_slug == slug)
    result = await session.execute(stmt)
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    run_id = await create_and_start_run(wf.id, trigger_type="webhook", trigger_payload=body.payload, background_tasks=background_tasks)
    return {"id": run_id}


@router.get("/blocks")
async def get_blocks():
    reg = list_blocks()
    return {"blocks": list(reg.keys())}


@router.get("/block-specs")
async def get_block_specs():
    return {"blocks": list_block_specs()}
