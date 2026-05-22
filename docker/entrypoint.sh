#!/usr/bin/env bash
set -euo pipefail

cd /app/deer-flow/backend
export PYTHONPATH="/app/deer-flow/backend:/app/deer-flow/backend/packages/harness:/app/deer-flow/overlay/backend:${PYTHONPATH:-}"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

exec uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001
