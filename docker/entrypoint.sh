#!/bin/bash
set -e

echo "===== Archon-DeerFlow Gateway ====="
echo "Python: $(python3 --version)"
echo "elan: $(elan --version 2>/dev/null || echo 'installed')"
echo "Lean: $(lean --version 2>/dev/null || echo 'installed')"
echo ""

# ── Runtime data ──
mkdir -p /app/backend/.deer-flow
mkdir -p /app/backend/.deer-flow/threads

export DEER_FLOW_PROJECT_ROOT=/app
export DEER_FLOW_HOME=/app/backend/.deer-flow
export DEER_FLOW_CONFIG_PATH=/app/config.yaml
export DEER_FLOW_EXTENSIONS_CONFIG_PATH=/app/extensions_config.json
export DEER_FLOW_CHANNELS_LANGGRAPH_URL=http://localhost:8001/api
export DEER_FLOW_CHANNELS_GATEWAY_URL=http://localhost:8001

echo "=== config.yaml ==="
cat /app/config.yaml | head -20
echo "..."

echo ""
echo "=== Starting Gateway on :8001 ==="
cd /app
exec uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --workers 2
