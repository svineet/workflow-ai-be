from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..blocks.base import RunContext
from ..blocks.registry import run_block
from ..db.models import Run, Workflow, NodeRun
from ..engine.graph import toposort, build_parent_child_maps
from ..services.gcs import GCSWriter
from ..services.http import create_http_client
from .logging import insert_log


async def execute_run(run_id: int, SessionFactory, gcs_bucket: str | None = None) -> None:
    async with SessionFactory() as session:  # type: AsyncSession
        run = await _load_run_with_workflow(session, run_id)
        if run is None:
            return

        await _mark_run_running(session, run.id)
        await session.commit()

        # Build graph and topo order
        from ..schemas.graph import Graph

        graph = Graph.model_validate(run.workflow.graph_json)
        order = toposort(graph)
        parents_map, _ = build_parent_child_maps(graph)

        outputs: Dict[str, Dict[str, Any]] = {}

        # Map tool edges per agent node
        tool_children: Dict[str, Dict[str, Any]] = {}
        for e in graph.edges:
            if getattr(e, "kind", "control") == "tool":
                if e.from_node not in tool_children:
                    tool_children[e.from_node] = []
                tool_children[e.from_node].append(e.to)

        # Shared context resources
        http_client = create_http_client()
        gcs = GCSWriter(bucket_name=gcs_bucket) if gcs_bucket else GCSWriter()

        async def logger(message: str, data: Dict[str, Any] | None = None, node_id: str | None = None) -> None:
            await insert_log(session, run.id, message, node_id=node_id, data=data)

        # Try to resolve user_id from run or workflow as we add multi-tenant support
        try:
            run_user_id = getattr(run, "user_id", None)
        except Exception:
            run_user_id = None
        try:
            workflow_user_id = getattr(run.workflow, "user_id", None) if getattr(run, "workflow", None) else None
        except Exception:
            workflow_user_id = None
        ctx = RunContext(gcs=gcs, http=http_client, logger=logger, user_id=run_user_id or workflow_user_id)

        try:
            for node_id in order:
                node = next(n for n in graph.nodes if n.id == node_id)

                # Skip tool nodes
                if str(node.type).startswith("tool."):
                    await logger(f"Skipping tool node {node.id} in main execution (invoked via agent tools)", node_id=node.id)
                    continue

                await logger(f"Starting node {node.id}", node_id=node.id)

                upstream_outputs = {pid: outputs[pid] for pid in parents_map.get(node.id, []) if pid in outputs}
                node_input: Dict[str, Any] = {
                    "settings": getattr(node, "settings", {}) or {},
                    "upstream": upstream_outputs,
                    "trigger": run.trigger_payload_json,
                    "node_id": node.id,
                }

                # Attach derived tools for agent nodes
                if str(node.type).startswith("agent.") and tool_children.get(node.id):
                    derived_tools = []
                    for tool_node_id in tool_children.get(node.id, []):
                        tnode = next((n for n in graph.nodes if n.id == tool_node_id), None)
                        if tnode is None:
                            continue
                        tsettings = getattr(tnode, "settings", {}) or {}
                        derived_tools.append({
                            "id": getattr(tnode, "id", tool_node_id),
                            "name": tsettings.get("name") or getattr(tnode, "id", tool_node_id),
                            "type": getattr(tnode, "type", ""),
                            "settings": tsettings,
                        })
                    node_input["__derived_tools_from_edges__"] = derived_tools

                await _mark_node_status(session, run.id, node.id, node.type, status="running")
                await session.commit()
                try:
                    result = await run_block(node.type, node_input, ctx)
                    outputs[node.id] = result
                    await _persist_node_success(session, run.id, node.id, node.type, node_input, result)
                    await session.commit()
                    await logger(f"Finished node {node.id}", node_id=node.id)
                except Exception as ex:
                    await _persist_node_error(session, run.id, node.id, node.type, node_input, ex)
                    await session.commit()
                    await logger(f"Node {node.id} failed: {ex}", {"error": str(ex)}, node_id=node.id)
                    raise

            await _mark_run_succeeded(session, run.id, outputs)
            await session.commit()
        except Exception:
            await _mark_run_failed(session, run.id, outputs)
            await session.commit()
        finally:
            await http_client.aclose()


async def _load_run_with_workflow(session: AsyncSession, run_id: int) -> Run | None:
    stmt = select(Run).where(Run.id == run_id).options()
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        return None
    # explicit load workflow
    await session.refresh(run, attribute_names=["workflow"])
    return run


async def _mark_run_running(session: AsyncSession, run_id: int) -> None:
    await session.execute(
        update(Run).where(Run.id == run_id).values(status="running", started_at=datetime.utcnow())
    )


async def _mark_run_succeeded(session: AsyncSession, run_id: int, outputs: Dict[str, Any]) -> None:
    await session.execute(
        update(Run).where(Run.id == run_id).values(status="succeeded", finished_at=datetime.utcnow(), outputs_json=outputs)
    )


async def _mark_run_failed(session: AsyncSession, run_id: int, outputs: Dict[str, Any]) -> None:
    await session.execute(
        update(Run).where(Run.id == run_id).values(status="failed", finished_at=datetime.utcnow(), outputs_json=outputs)
    )


async def _mark_node_status(session: AsyncSession, run_id: int, node_id: str, node_type: str, *, status: str) -> None:
    await session.execute(
        insert(NodeRun).values(
            run_id=run_id, node_id=node_id, node_type=node_type, status=status, started_at=datetime.utcnow() if status == "running" else None
        )
    )


async def _persist_node_success(session: AsyncSession, run_id: int, node_id: str, node_type: str, input_payload: Dict[str, Any], output_payload: Dict[str, Any]) -> None:
    from sqlalchemy import update

    await session.execute(
        update(NodeRun)
        .where(NodeRun.run_id == run_id, NodeRun.node_id == node_id)
        .values(status="succeeded", finished_at=datetime.utcnow(), input_json=input_payload, output_json=output_payload)
    )


async def _persist_node_error(session: AsyncSession, run_id: int, node_id: str, node_type: str, input_payload: Dict[str, Any], ex: Exception) -> None:
    from sqlalchemy import update

    await session.execute(
        update(NodeRun)
        .where(NodeRun.run_id == run_id, NodeRun.node_id == node_id)
        .values(status="failed", finished_at=datetime.utcnow(), input_json=input_payload, error_json={"message": str(ex)})
    )
