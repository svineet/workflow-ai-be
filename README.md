# Workflow AI Backend

FastAPI backend for node-based workflow orchestration with async execution, logging, agent tools, and Supabase-based auth.

## Prerequisites
- Python 3.11+
- PostgreSQL (Supabase recommended)
- pip and virtualenv (optional if using Docker)

## Environment Variables
Create `.env.dev` (and `.env.example`) with at least:

- DATABASE_URL: `postgresql+asyncpg://postgres:<PASS>@db.<PROJECT>.supabase.co:5432/postgres?sslmode=require`
- SUPABASE_JWT_SECRET: HS256 secret from Supabase
- CORS_ORIGINS: e.g. `http://localhost:5173`
- FRONTEND_BASE_URL: e.g. `http://localhost:5173`
- Optional:
  - OPENAI_API_KEY
  - COMPOSIO_API_KEY
  - COMPOSIO_TOOLKITS (CSV, e.g. `GMAIL,GOOGLE_DRIVE`)
  - COMPOSIO_AUTH_CONFIGS (JSON map of toolkit→authConfigId)
  - GCS_BUCKET

## Install & Run (local)
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
ENV_FILE=.env.dev uvicorn app.server.main:app --host 0.0.0.0 --port 8000
```

Or use the provided script:
```bash
chmod +x scripts/run_local.sh
./scripts/run_local.sh
```

Health check:
```bash
curl http://localhost:8000/healthz
```

## Database Migrations (Alembic)
The repo is configured to read `DATABASE_URL` and auto-derive a sync DSN for Alembic.
```bash
alembic upgrade head
# Optional reset
alembic downgrade base && alembic upgrade head
```

## Docker
Production-like image:
```bash
docker build -t workflow-ai-be -f Dockerfile .
docker run --rm -p 8000:8000 --env-file .env.dev workflow-ai-be
```
Dev (autoreload):
```bash
docker build -t workflow-ai-be-dev -f Dockerfile.local .
docker run --rm -p 8000:8000 --env-file .env.dev -v "$PWD/app:/app/app" workflow-ai-be-dev
```

Docker Compose with local Postgres (optional):
```bash
docker compose -f docker-compose.local.yml --env-file .env.dev up -d --build
```

## Auth (Supabase)
- Backend verifies HS256 access tokens using `SUPABASE_JWT_SECRET`.
- Include `Authorization: Bearer <access_token>` from Supabase client.
- Test:
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/auth/me
```

## Composio (optional)
- Set `COMPOSIO_API_KEY`, `COMPOSIO_TOOLKITS`, `COMPOSIO_AUTH_CONFIGS`.
- Authorize via `/integrations/composio/authorize` (requires Authorization header).
- Callback persists accounts per user using a signed `state` (includes uid).

## Key Endpoints
- GET `/healthz`
- Workflows: CRUD + `/workflows/{id}/run`
- Runs: list/get/logs/stream
- Assistant: `/assistant/new`, `/assistant/new/stream`
- Auth: `/auth/me`
- Integrations: `/integrations`, `/integrations/composio/*`

## Deployment
### Render (recommended for simplicity)
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.server.main:app --host 0.0.0.0 --port $PORT`
- Set env vars in the dashboard; ensure `DATABASE_URL` uses `+asyncpg` and `?sslmode=require`.
- Run Alembic migrations once from your machine or CI.

### Cloud Run (alternative)
- Use the same Dockerfile. Ensure secrets/envs are set. Deploy with `gcloud run deploy ...`.

## Troubleshooting
- DB connect errors: verify `DATABASE_URL` uses `+asyncpg` and `sslmode=require`.
- JWT 401: check `SUPABASE_JWT_SECRET` and token freshness.
- SSE headers: use EventSource polyfill to send Authorization header.
- Composio callback 500: ensure authorize state contains uid; backend updated accordingly.
