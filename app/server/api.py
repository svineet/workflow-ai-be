from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import blocks  # noqa: F401 — ensure registry is populated
from ..blocks.registry import list_blocks, list_block_specs
from ..db.models import Log, Run, Workflow, RunStatusEnum, NodeRun
from ..db.session import SessionFactory
from ..engine.graph import toposort
from ..schemas.graph import Graph
from ..schemas.run import RunCreate
from ..engine.orchestrator import create_and_start_run
from starlette.responses import StreamingResponse
import asyncio
import json

router = APIRouter()


async def get_session() -> AsyncSession:
    async with SessionFactory() as session:
        yield session


class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    webhook_slug: Optional[str] = None
    graph: Graph


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    webhook_slug: Optional[str] = None
    graph: Optional[Graph] = None


@router.get("/workflows")
async def list_workflows(session: AsyncSession = Depends(get_session)):
    stmt = select(Workflow).order_by(Workflow.id.asc())
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "webhook_slug": w.webhook_slug,
            "created_at": w.created_at.isoformat(),
        }
        for w in rows
    ]


@router.get("/runs")
async def list_runs(workflow_id: Optional[int] = None, status: Optional[str] = None, session: AsyncSession = Depends(get_session)):
    stmt = select(Run)
    if workflow_id is not None:
        stmt = stmt.where(Run.workflow_id == workflow_id)
    if status is not None:
        try:
            status_enum = RunStatusEnum(status)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid status")
        stmt = stmt.where(Run.status == status_enum)
    stmt = stmt.order_by(Run.id.desc())

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "workflow_id": r.workflow_id,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "trigger_type": r.trigger_type,
        }
        for r in rows
    ]


@router.post("/workflows")
async def create_workflow(body: WorkflowCreate, session: AsyncSession = Depends(get_session)):
    stmt = insert(Workflow).values(
        name=body.name,
        description=body.description,
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
        "description": wf.description,
        "webhook_slug": wf.webhook_slug,
        "graph": wf.graph_json,
        "created_at": wf.created_at.isoformat(),
    }


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: int, body: WorkflowUpdate, session: AsyncSession = Depends(get_session)):
    values: Dict[str, Any] = {}
    if body.name is not None:
        values["name"] = body.name
    if body.description is not None:
        values["description"] = body.description
    if body.webhook_slug is not None:
        values["webhook_slug"] = body.webhook_slug
    if body.graph is not None:
        values["graph_json"] = body.graph.model_dump(by_alias=True)

    if not values:
        return {"updated": False}

    await session.execute(update(Workflow).where(Workflow.id == workflow_id).values(**values))
    await session.commit()
    return {"updated": True}


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    result = await session.execute(stmt)
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await session.delete(wf)
    await session.commit()
    return {"deleted": True}


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

    current_node_id: Optional[str] = None
    # Prefer running node if any; otherwise the most recently started node without finished_at
    nr_stmt = (
        select(NodeRun)
        .where(NodeRun.run_id == run.id, NodeRun.status == "running")
        .order_by(NodeRun.started_at.desc())
        .limit(1)
    )
    nr_res = await session.execute(nr_stmt)
    nr = nr_res.scalars().first()
    if nr is None:
        nr_stmt2 = (
            select(NodeRun)
            .where(NodeRun.run_id == run.id)
            .order_by(NodeRun.started_at.desc())
            .limit(1)
        )
        nr_res2 = await session.execute(nr_stmt2)
        nr2 = nr_res2.scalars().first()
        if nr2 is not None and nr2.finished_at is None:
            current_node_id = nr2.node_id
    else:
        current_node_id = nr.node_id

    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "trigger_type": run.trigger_type,
        "outputs_json": run.outputs_json,
        "current_node_id": current_node_id,
    }


@router.get("/runs/{run_id}/logs")
async def get_run_logs(run_id: int, after_id: Optional[int] = None, session: AsyncSession = Depends(get_session)):
    stmt = select(Log).where(Log.run_id == run_id)
    if after_id is not None:
        stmt = stmt.where(Log.id > after_id)
    stmt = stmt.order_by(Log.ts.asc())
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


@router.get("/runs/{run_id}/logs/stream")
async def stream_run(run_id: int):
    async def event_gen():
        last_id = 0
        last_status: Optional[str] = None
        while True:
            async with SessionFactory() as session:  # type: AsyncSession
                # first, logs since last id
                log_stmt = select(Log).where(Log.run_id == run_id, Log.id > last_id).order_by(Log.id.asc())
                log_res = await session.execute(log_stmt)
                new_rows = log_res.scalars().all()
                for row in new_rows:
                    entry = {
                        'id': row.id,
                        'run_id': row.run_id,
                        'node_id': row.node_id,
                        'ts': row.ts.isoformat(),
                        'level': row.level,
                        'message': row.message,
                        'data': row.data_json,
                    }
                    yield f"data: {json.dumps({'type':'log', 'entry': entry})}\n\n"
                    msg = row.message or ''
                    if msg.startswith('Starting node') and row.node_id:
                        yield f"data: {json.dumps({'type':'node_started', 'node_id': row.node_id})}\n\n"
                    if (msg.startswith('Finished node') or 'failed' in msg) and row.node_id:
                        evt = 'node_finished' if msg.startswith('Finished node') else 'node_failed'
                        yield f"data: {json.dumps({'type':evt, 'node_id': row.node_id})}\n\n"
                    last_id = max(last_id, row.id)

                # then, status update
                run_res = await session.execute(select(Run).where(Run.id == run_id))
                run = run_res.scalar_one_or_none()
                if run is None:
                    yield f"data: {json.dumps({'type':'status', 'status':'not_found'})}\n\n"
                    break
                status = run.status.value if hasattr(run.status, 'value') else str(run.status)
                if status != last_status:
                    last_status = status
                    yield f"data: {json.dumps({'type':'status', 'status':status})}\n\n"
                if status in ('succeeded', 'failed'):
                    break

            await asyncio.sleep(1.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


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
