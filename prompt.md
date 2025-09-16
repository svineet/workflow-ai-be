Build a FastAPI backend for an AI-native workflow runner with brutally simple architecture: one mutable graph per workflow, background execution in-process, logs per node, artifacts in GCS. Clean separation between server, engine, and blocks. Use FastAPI, SQLAlchemy 2.x (async), Pydantic v2, httpx, google-cloud-storage, asyncpg.

Directory structure (backend only)
backend/
  app/
    server/        # HTTP: routers, settings, deps, CORS
    engine/        # workflow core: graph, orchestrator, executor, logging
    blocks/        # block abstraction + registry + std blocks
      std/
    db/            # models + session (SQLAlchemy async)
    services/      # gcs + http client factories
    schemas/       # Pydantic models (Graph, Run)
    __init__.py
  requirements.txt
  Dockerfile
  Dockerfile.local

Data model (no versioning)

workflows(id, name, webhook_slug, graph_json JSON, created_at)

graph_json is the single active graph. Updates overwrite it.

runs(id, workflow_id, status ENUM('pending','running','succeeded','failed'), started_at, finished_at, trigger_type, trigger_payload_json, outputs_json)

node_runs(id, run_id, node_id, node_type, status, started_at, finished_at, input_json, output_json, error_json)

logs(id, run_id, node_id, ts, level, message, data_json)

No snapshots, no versions. FE can handle undo/redo ephemerally for now.

Graph schema (Pydantic)

Node { id: str, type: str, params: dict = {} }

Edge { id: str, from_node: str (alias "from"), to: str }

Graph { nodes: list[Node], edges: list[Edge] }

Validate: unique node IDs, all edge endpoints exist, acyclic (topo sort).

Blocks (decorator registry)

blocks/base.py:

RunContext(gcs, http, logger) for I/O + logging

Block contract: async def run(input: dict, ctx: RunContext) -> dict

blocks/registry.py:

@register("type") decorator → _REGISTRY[type] = callable

run_block(type, input, ctx) dispatcher

list_blocks() for /blocks

Std blocks (blocks/std/):

start — returns { data: params.payload ?? trigger_payload }

http.request — {method,url,headers?,body?} -> {status,headers,data}

gcs.write — {path, content?, as_json?} -> {gcs_uri,size}

llm.simple — {prompt, model?} with fallback (uppercase) if no API key

Engine

engine/graph.py: topo sort + parent/child maps; raise on cycles.

engine/logging.py: helper to insert structured logs.

engine/executor.py:

execute_run(run_id, SessionFactory, gcs_bucket):

Load Run + workflow.graph_json (single mutable graph).

Mark run running; iterate nodes in topo order.

Build node_input = { "params": node.params, "upstream": {parentId: output}, "trigger": run.trigger_payload_json }.

Call run_block; persist NodeRun input/output/error; write logs.

On first exception, mark run failed, keep partial outputs.

On success, mark succeeded and store outputs_json = { node_id: output }.

Use one shared httpx.AsyncClient and a GCS wrapper in RunContext.

engine/orchestrator.py:

create_and_start_run(workflow_id, trigger_type="manual", trigger_payload=None, background_tasks):

Insert Run(pending); enqueue execute_run via FastAPI BackgroundTasks.

Services

services/gcs.py: thin wrapper → write_bytes(path, data, content_type) -> "gs://...".

services/http.py: factory for httpx.AsyncClient(timeout=30).

Server

server/settings.py: env: DATABASE_URL, GCS_BUCKET, CORS_ORIGINS (CSV), optional OPENAI_API_KEY, PORT.

server/middleware.py: CORS using CORS_ORIGINS.

server/api.py: routes below.

server/main.py: create app, include routers, add CORS, /healthz, and create tables on startup (MVP; Alembic later).

API design (super minimal)

Workflows

POST /workflows — create workflow (body: {name, webhook_slug?, graph}); stores graph_json.

GET /workflows/{id} — fetch workflow (incl. graph_json).

PUT /workflows/{id} — overwrite graph_json (and/or webhook_slug, name). No versioning.

POST /validate-graph — optional: server-side graph validation (structure + acyclic).

Runs

POST /workflows/{id}/run — start a run on the workflow’s current graph (body: {start_input?}).

GET /runs/{id} — status, timings, final outputs_json.

GET /runs/{id}/logs — chronological logs (run + node).

Triggers

POST /hooks/{slug} — start run for workflow with matching webhook_slug (body: {payload}).

Blocks

GET /blocks — list registered block types (for FE palette/assistant).

Health

GET /healthz — readiness.