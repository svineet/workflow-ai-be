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

        # Build graph and topo order from workflow.graph_json
        from ..schemas.graph import Graph

        graph = Graph.model_validate(run.workflow.graph_json)
        order = toposort(graph)
        parents_map, _ = build_parent_child_maps(graph)

        outputs: Dict[str, Dict[str, Any]] = {}

        # Shared context resources
        http_client = create_http_client()
        gcs = GCSWriter(bucket_name=gcs_bucket) if gcs_bucket else GCSWriter()

        async def logger(message: str, data: Dict[str, Any] | None = None, node_id: str | None = None) -> None:
            await insert_log(session, run.id, message, node_id=node_id, data=data)

        ctx = RunContext(gcs=gcs, http=http_client, logger=logger)

        try:
            for node_id in order:
                node = next(n for n in graph.nodes if n.id == node_id)
                await logger(f"Starting node {node.id}", node_id=node.id)

                upstream_outputs = {pid: outputs[pid] for pid in parents_map.get(node.id, []) if pid in outputs}
                node_input: Dict[str, Any] = {
                    "params": node.params,
                    "upstream": upstream_outputs,
                    "trigger": run.trigger_payload_json,
                }

                await _mark_node_status(session, run.id, node.id, node.type, status="running")
                try:
                    result = await run_block(node.type, node_input, ctx)
                    outputs[node.id] = result
                    await _persist_node_success(session, run.id, node.id, node.type, node_input, result)
                    await logger(f"Finished node {node.id}", node_id=node.id)
                except Exception as ex:
                    await _persist_node_error(session, run.id, node.id, node.type, node_input, ex)
                    await logger(f"Node {node.id} failed: {ex}", {"error": str(ex)}, node_id=node.id)
                    raise

            await _mark_run_succeeded(session, run.id, outputs)
        except Exception:
            await _mark_run_failed(session, run.id, outputs)
        finally:
            await http_client.aclose()
            await session.commit()


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
