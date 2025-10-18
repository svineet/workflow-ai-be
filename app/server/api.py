from __future__ import annotations

from typing import Any, Dict, Optional
from collections import OrderedDict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import blocks  # noqa: F401 — ensure registry is populated
from ..blocks.registry import list_blocks, list_block_specs
from ..db.models import Log, Run, Workflow, RunStatusEnum, NodeRun, ComposioAccount
from ..db.session import SessionFactory
from ..engine.graph import toposort
from ..schemas.graph import Graph
from ..schemas.run import RunCreate
from ..engine.orchestrator import create_and_start_run
from ..server.settings import settings
from ..server.middleware import get_current_user_id, require_user_id
from ..services.assistant import create_workflow_from_prompt, stream_graph_from_prompt
from sqlalchemy import and_
from ..services.composio import get_composio_client
from starlette.responses import StreamingResponse, RedirectResponse
import asyncio
import json
import secrets
import re
import hmac
import hashlib
import base64

router = APIRouter()


async def get_session() -> AsyncSession:
    async with SessionFactory() as session:
        yield session


def _current_user_id(request: Request) -> str:
    # Prefer Supabase-authenticated user; fallback to system-user for unauthenticated public endpoints
    try:
        uid = getattr(request.state, "user_id", None)
        if isinstance(uid, str) and uid:
            return uid
    except Exception:
        pass
    return "system-user"


def _sign_state(data: Dict[str, Any]) -> str:
    raw = json.dumps(data).encode("utf-8")
    secret = (settings.SUPABASE_JWT_SECRET or "dev").encode("utf-8")
    mac = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return f"{base64.urlsafe_b64encode(raw).decode('ascii')}.{mac}"


def _parse_state(state: str) -> Dict[str, Any]:
    try:
        if "." in state:
            b64, mac = state.split(".", 1)
            raw = base64.urlsafe_b64decode(b64.encode("ascii"))
            secret = (settings.SUPABASE_JWT_SECRET or "dev").encode("utf-8")
            expect = hmac.new(secret, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, expect):
                return {}
            return json.loads(raw.decode("utf-8"))
        # Fallback legacy (unsigned JSON)
        return json.loads(state)
    except Exception:
        return {}


def _frontend_base_url() -> str:
    # Prefer explicit env
    if settings.FRONTEND_BASE_URL:
        return settings.FRONTEND_BASE_URL.rstrip("/")
    # Then first CORS origin if set
    if settings.CORS_ORIGINS and settings.CORS_ORIGINS[0] != "*":
        return settings.CORS_ORIGINS[0].rstrip("/")
    # Fallback to default Vite dev server
    return "http://localhost:5173"


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


def _validate_and_normalize_agent_tools(graph: Graph) -> Dict[str, Any]:
    from ..blocks.registry import get_block_class

    # Work on a plain dict for mutation
    gdict: Dict[str, Any] = graph.model_dump(by_alias=True)

    # Build quick lookup for tool compatibility
    def is_tool_compatible(type_name: str) -> bool:
        cls = get_block_class(type_name)
        if cls is None:
            return False
        if getattr(cls, "tool_compatible", False):
            return True
        if type_name.startswith("tool."):
            return True
        extras = cls.extras() if hasattr(cls, "extras") and callable(getattr(cls, "extras")) else None
        if isinstance(extras, dict) and extras.get("toolCompatible") is True:
            return True
        return False

    # Validate each agent node
    for node in gdict.get("nodes", []):
        type_name = node.get("type")
        cls = get_block_class(type_name)
        is_agent = (type_name or "").startswith("agent.") or (cls is not None and getattr(cls, "kind", "") == "agent")
        if not is_agent:
            continue
        settings = node.get("settings") or {}
        tools = settings.get("tools") or []
        # Enforce unique names
        seen: set[str] = set()
        normalized_tools: list[Dict[str, Any]] = []
        for t in tools:
            tname = (t or {}).get("name")
            ttype = (t or {}).get("type")
            tsettings = (t or {}).get("settings") or {}
            if not tname or not isinstance(tname, str):
                raise HTTPException(status_code=400, detail=f"Agent node {node.get('id')}: tool missing valid 'name'")
            if tname in seen:
                raise HTTPException(status_code=400, detail=f"Agent node {node.get('id')}: duplicate tool name '{tname}'")
            seen.add(tname)
            if not ttype or not isinstance(ttype, str):
                raise HTTPException(status_code=400, detail=f"Agent node {node.get('id')}: tool '{tname}' missing valid 'type'")
            if not is_tool_compatible(ttype):
                raise HTTPException(status_code=400, detail=f"Agent node {node.get('id')}: tool '{tname}' type '{ttype}' is not recognized as tool-compatible")
            # Validate settings against tool schema if available
            tcls = get_block_class(ttype)
            if tcls is None:
                raise HTTPException(status_code=400, detail=f"Agent node {node.get('id')}: unknown tool type '{ttype}'")
            Model = getattr(tcls, "settings_model", None)
            if Model is not None:
                try:
                    validated = Model.model_validate(tsettings)
                    tsettings = validated.model_dump()
                except Exception as ex:
                    raise HTTPException(status_code=400, detail=f"Agent node {node.get('id')}: tool '{tname}' settings invalid: {ex}")
            normalized_tools.append({"name": tname, "type": ttype, "settings": tsettings})
        # Write back normalized tools
        settings["tools"] = normalized_tools
        node["settings"] = settings

    return gdict


def _extract_json_object(text: str) -> Dict[str, Any]:
    # Try direct JSON first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try code fence ```json ... ```
    fence = re.search(r"```json\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass
    # Try first balanced brace substring
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
    raise ValueError("Unable to extract JSON graph from model output")


class AssistantNewBody(BaseModel):
    prompt: str
    model: Optional[str] = None


@router.post("/assistant/new")
async def assistant_new(body: AssistantNewBody, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    try:
        new_id, cached = await create_workflow_from_prompt(session, body.prompt, body.model, user_id=user_id)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    resp: Dict[str, Any] = {"id": new_id}
    if cached:
        resp["cached"] = True
    return resp


@router.post("/assistant/new/stream")
async def assistant_new_stream(body: AssistantNewBody, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    async def event_gen():
        async for chunk in stream_graph_from_prompt(session, body.prompt, body.model, user_id=user_id):
            try:
                yield f"data: {json.dumps(chunk)}\n\n"
            except Exception:
                yield f"data: {json.dumps({'type':'error','message':'serialization_failed'})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/workflows")
async def list_workflows(session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    stmt = select(Workflow).where((Workflow.user_id == user_id) | (Workflow.user_id.is_(None))).order_by(Workflow.id.asc())
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
async def list_runs(
    workflow_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    before_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(require_user_id),
):
    stmt = select(Run).where((Run.user_id == user_id) | (Run.user_id.is_(None)))
    if workflow_id is not None:
        stmt = stmt.where(Run.workflow_id == workflow_id)
    if status is not None:
        try:
            status_enum = RunStatusEnum(status)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid status")
        stmt = stmt.where(Run.status == status_enum)
    if before_id is not None:
        stmt = stmt.where(Run.id < before_id)
    stmt = stmt.order_by(Run.id.desc())

    # When limit is provided, use cursor-style pagination and return an envelope
    if limit is not None:
        if limit <= 0:
            raise HTTPException(status_code=400, detail="limit must be positive")
        # Hard cap to avoid overly large queries
        page_size = min(limit, 100)
        result = await session.execute(stmt.limit(page_size + 1))
        rows_all = result.scalars().all()
        rows = rows_all[:page_size]
        has_more = len(rows_all) > page_size
        items = [
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
        next_cursor = rows[-1].id if has_more and rows else None
        return {"items": items, "next_cursor": next_cursor, "has_more": has_more}

    # Default: preserve legacy behavior returning a simple list
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
async def create_workflow(body: WorkflowCreate, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    # Validate/normalize agent tools per backend rules
    gdict = _validate_and_normalize_agent_tools(body.graph)
    stmt = insert(Workflow).values(
        name=body.name,
        description=body.description,
        webhook_slug=body.webhook_slug,
        graph_json=gdict,
        user_id=user_id,
    )
    result = await session.execute(stmt)
    await session.commit()
    return {"id": int(result.inserted_primary_key[0])}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: int, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    stmt = select(Workflow).where(Workflow.id == workflow_id, (Workflow.user_id == user_id) | (Workflow.user_id.is_(None)))
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
async def update_workflow(workflow_id: int, body: WorkflowUpdate, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    values: Dict[str, Any] = {}
    if body.name is not None:
        values["name"] = body.name
    if body.description is not None:
        values["description"] = body.description
    if body.webhook_slug is not None:
        values["webhook_slug"] = body.webhook_slug
    if body.graph is not None:
        values["graph_json"] = _validate_and_normalize_agent_tools(body.graph)

    if not values:
        return {"updated": False}

    await session.execute(update(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id).values(**values))
    await session.commit()
    return {"updated": True}


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: int, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    stmt = select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id)
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
async def validate_graph(body: ValidateGraphBody, user_id: str = Depends(require_user_id)):
    _ = toposort(body.graph)
    return {"valid": True}


@router.post("/workflows/{workflow_id}/run")
async def start_run(workflow_id: int, body: RunCreate | None = None, background_tasks: BackgroundTasks = None, user_id: str = Depends(require_user_id)):
    background_tasks = background_tasks or BackgroundTasks()
    # Ensure workflow is accessible to user
    async with SessionFactory() as session:  # type: AsyncSession
        wf_res = await session.execute(
            select(Workflow).where(Workflow.id == workflow_id, (Workflow.user_id == user_id) | (Workflow.user_id.is_(None)))
        )
        wf_ok = wf_res.scalar_one_or_none()
        if wf_ok is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
    run_id = await create_and_start_run(
        workflow_id,
        trigger_type="manual",
        trigger_payload=(body.start_input if body else None) or {},
        background_tasks=background_tasks,
        user_id=user_id,
    )
    return {"id": run_id}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    stmt = select(Run).where(Run.id == run_id, (Run.user_id == user_id) | (Run.user_id.is_(None)))
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
async def get_run_logs(run_id: int, after_id: Optional[int] = None, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    # Enforce ownership
    run_res = await session.execute(select(Run).where(Run.id == run_id, (Run.user_id == user_id) | (Run.user_id.is_(None))))
    run = run_res.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
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


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int, user_id: str = Depends(require_user_id)):
    # Validate ownership before starting stream
    async with SessionFactory() as session:
        chk = await session.execute(select(Run).where(Run.id == run_id, (Run.user_id == user_id) | (Run.user_id.is_(None))))
        if chk.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Run not found")
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


# Alias route to satisfy clients/tests expecting /runs/{run_id}/logs/stream
@router.get("/runs/{run_id}/logs/stream")
async def stream_run_logs_alias(run_id: int, user_id: str = Depends(require_user_id)):
    return await stream_run(run_id, user_id)  # type: ignore[arg-type]


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


class ComposioAuthorizeBody(BaseModel):
    toolkit: str


@router.post("/integrations/composio/authorize")
async def composio_authorize(body: ComposioAuthorizeBody, request: Request, user_id: str = Depends(require_user_id)):
    client = get_composio_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Composio is not configured. Set COMPOSIO_API_KEY and install composio.")
    # user_id provided by dependency
    auth_config_id = settings.COMPOSIO_AUTH_CONFIGS.get(body.toolkit)
    if not auth_config_id:
        raise HTTPException(status_code=400, detail="Unknown toolkit or COMPOSIO_AUTH_CONFIGS missing for requested toolkit")
    state = _sign_state({"tk": body.toolkit, "uid": user_id, "nonce": secrets.token_hex(8)})
    cb = str(request.url_for("composio_callback"))
    try:
        # Prefer hosted connect link for OAuth/API-Key flows
        conn_req = client.connected_accounts.link(user_id, auth_config_id, callback_url=f"{cb}?state={state}&toolkit={body.toolkit}")
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Failed to create connect link: {ex}")
    return {"redirect_url": getattr(conn_req, 'redirect_url', None), "connection_request_id": getattr(conn_req, "id", None)}


@router.get("/integrations/composio/callback")
async def composio_callback(
    connection_request_id: Optional[str] = None,
    toolkit: Optional[str] = None,
    state: Optional[str] = None,
    connected_account_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    client = get_composio_client()
    if client is None:
        raise HTTPException(status_code=400, detail="Composio is not configured. Set COMPOSIO_API_KEY and install composio.")
    if state is None or toolkit is None:
        raise HTTPException(status_code=400, detail="Missing state/toolkit")
    parsed = _parse_state(state)
    user_id = (parsed or {}).get("uid")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=400, detail="Invalid state")
    # Wait for connection using request id if provided
    connected = None
    if connection_request_id:
        try:
            connected = client.connected_accounts.wait_for_connection(connection_request_id)
        except Exception:
            connected = None
    # Extract id robustly
    candidate_ids: list[str] = []
    if connected is not None:
        for attr in ("connected_account_id", "id", "account_id"):
            try:
                val = getattr(connected, attr, None)
                if isinstance(val, str) and val:
                    candidate_ids.append(val)
            except Exception:
                pass
        # Also check dict-like
        if hasattr(connected, "get") and callable(getattr(connected, "get")):
            for k in ("connected_account_id", "id", "account_id"):
                try:
                    val = connected.get(k)
                    if isinstance(val, str) and val:
                        candidate_ids.append(val)
                except Exception:
                    pass
    if connected_account_id:
        candidate_ids.insert(0, connected_account_id)
    # Deduplicate while preserving order
    seen: set[str] = set()
    resolved_id = None
    for cid in candidate_ids:
        if cid in seen:
            continue
        seen.add(cid)
        resolved_id = cid
        break

    frontend = _frontend_base_url()
    success_url = f"{frontend}/integrations/success"

    if not resolved_id:
        # No connected id available; redirect but do not persist
        return RedirectResponse(url=success_url)

    await session.execute(
        insert(ComposioAccount).values(
            user_id=user_id,
            toolkit=toolkit,
            connected_account_id=resolved_id,
            status="active",
        )
    )
    await session.commit()
    return RedirectResponse(url=success_url)


@router.get("/integrations/composio/accounts")
async def list_composio_accounts(toolkit: Optional[str] = None, session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    stmt = select(ComposioAccount).where(ComposioAccount.user_id == user_id)
    if toolkit:
        stmt = stmt.where(ComposioAccount.toolkit == toolkit)
    res = await session.execute(stmt)
    rows = res.scalars().all()
    return [
        {
            "id": r.id,
            "toolkit": r.toolkit,
            "connected_account_id": r.connected_account_id,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/integrations")
async def list_integrations(session: AsyncSession = Depends(get_session), user_id: str = Depends(require_user_id)):
    configured_toolkits = settings.COMPOSIO_TOOLKITS
    # Also include any toolkits that have accounts in DB
    tk_stmt = select(ComposioAccount.toolkit).where(ComposioAccount.user_id == user_id).distinct()
    tk_res = await session.execute(tk_stmt)
    db_toolkits = [row[0] for row in tk_res.all()]
    # Preserve configured order, then append any others from DB
    ordered_toolkits: list[str] = list(dict.fromkeys(list(configured_toolkits) + db_toolkits))

    result: list[Dict[str, Any]] = []
    for tk in ordered_toolkits:
        stmt = select(ComposioAccount).where(ComposioAccount.user_id == user_id, ComposioAccount.toolkit == tk)
        res = await session.execute(stmt)
        rows = res.scalars().all()
        result.append({
            "provider": "composio",
            "toolkit": tk,
            "connected": len(rows) > 0,
            "accounts": [
                {
                    "id": r.id,
                    "connected_account_id": r.connected_account_id,
                    "status": r.status,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        })
    return {"integrations": result}
