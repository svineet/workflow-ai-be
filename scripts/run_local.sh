#!/usr/bin/env bash
set -euo pipefail

# Project root
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
cd "$dir"

IMAGE_NAME=${IMAGE_NAME:-workflow-ai-be-dev}
CONTAINER_NAME=${CONTAINER_NAME:-workflow-ai-be-dev}
ENV_FILE_PATH=${ENV_FILE:-.env.dev}

echo "[run_local] Building image $IMAGE_NAME from Dockerfile.local..."
docker build -t "$IMAGE_NAME" -f Dockerfile.local .

echo "[run_local] Stopping old container if present..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "[run_local] Starting container with .env from $ENV_FILE_PATH and live-reload mount..."
exec docker run \
  --name "$CONTAINER_NAME" \
  --rm \
  -p 8000:8000 \
  --env-file "$ENV_FILE_PATH" \
  -v "$PWD/app:/app/app" \
  "$IMAGE_NAME"
