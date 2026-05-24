#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# archon-deerflow gateway entrypoint
# Runs the DeerFlow Gateway with our Phase 1-6 workflow graphs registered.
# ---------------------------------------------------------------------------
set -euo pipefail

DEERFLOW_HOME="${DEERFLOW_HOME:-/app/deer-flow}"
DEERFLOW_BACKEND="${DEERFLOW_HOME}/backend"
OVERLAY_HOME="${DEERFLOW_HOME}/overlay"

cd "${DEERFLOW_BACKEND}"

# ── PYTHONPATH: deerflow-harness SDK + our overlay workflows ──
export PYTHONPATH="${DEERFLOW_BACKEND}:${DEERFLOW_BACKEND}/packages/harness:${OVERLAY_HOME}/backend:${PYTHONPATH:-}"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# ── Data directories ──
mkdir -p "${DEERFLOW_BACKEND}/data"
mkdir -p /mnt/user-data/{workspace,uploads,outputs} 2>/dev/null || true

echo "=== archon-deerflow gateway ==="
echo "  Python:       $(python3 --version)"
echo "  DeerFlow:     ${DEERFLOW_HOME}"
echo "  Overlay:      ${OVERLAY_HOME}"
echo "  Graphs:       $(python3 -c "import json; g=json.loads(open('langgraph.json').read()); print(', '.join(g.get('graphs',{}).keys()))" 2>/dev/null || echo 'N/A')"
echo "  Listen:       ${GATEWAY_LISTEN_HOST:-0.0.0.0}:${GATEWAY_LISTEN_PORT:-8001}"
echo "================================"

exec python3 -m uvicorn app.gateway.app:app \
    --host "${GATEWAY_LISTEN_HOST:-0.0.0.0}" \
    --port "${GATEWAY_LISTEN_PORT:-8001}"
