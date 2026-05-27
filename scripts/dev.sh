#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# archon-deerflow local development server (no Docker)
#
# Usage:
#   ./scripts/dev.sh              # Gateway only, port 8001 (hot reload)
#   ./scripts/dev.sh --full       # Full stack: nginx:2026 + frontend:3000 + gateway:8001
#   ./scripts/dev.sh --port 9000  # Custom port
#   ./scripts/dev.sh --no-clone   # Skip clone (deer-flow/ already exists)
#
# Prerequisites: Python 3.12+, Node.js 22+/pnpm, git, nginx, ripgrep
# Optional:       Lean 4 toolchain (elan)
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEER_FLOW_REPO="${DEER_FLOW_REPO:-https://github.com/bytedance/deer-flow.git}"
DEER_FLOW_REF="${DEER_FLOW_REF:-main}"
DEERFLOW_HOME="${REPO_ROOT}/deer-flow"
DEERFLOW_BACKEND="${DEERFLOW_HOME}/backend"
DEERFLOW_FRONTEND="${DEERFLOW_HOME}/frontend"
OVERLAY_BACKEND="${REPO_ROOT}/overlay/backend"

PORT="${GATEWAY_LISTEN_PORT:-8001}"
FRONTEND_PORT=3000
NGINX_PORT=2026
DO_CLONE=true
FULL_STACK=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)   PORT="$2"; shift 2 ;;
        --full)   FULL_STACK=true; shift ;;
        --no-clone) DO_CLONE=false; shift ;;
        *) shift ;;
    esac
done

# ── Clone deer-flow from GitHub ──
if $DO_CLONE && [[ ! -d "${DEERFLOW_HOME}/backend" ]]; then
    echo "[dev] Cloning deer-flow from ${DEER_FLOW_REPO} @ ${DEER_FLOW_REF} ..."
    git clone --depth 1 --branch "${DEER_FLOW_REF}" "${DEER_FLOW_REPO}" "${DEERFLOW_HOME}"
fi

# ── Register overlay ──
cp "${OVERLAY_BACKEND}/langgraph.json" "${DEERFLOW_BACKEND}/langgraph.json" 2>/dev/null || true
cp -r "${OVERLAY_BACKEND}" "${DEERFLOW_HOME}/overlay/backend" 2>/dev/null || true
cp "${REPO_ROOT}/config.yaml" "${DEERFLOW_BACKEND}/config.yaml" 2>/dev/null || true
cp "${REPO_ROOT}/extensions_config.json" "${DEERFLOW_BACKEND}/extensions_config.json" 2>/dev/null || true
mkdir -p "${DEERFLOW_HOME}/skills" && cp -r "${REPO_ROOT}/skills/"* "${DEERFLOW_HOME}/skills/" 2>/dev/null || true
mkdir -p "${REPO_ROOT}/data/checkpoints"
mkdir -p /mnt/user-data/workspace /mnt/user-data/uploads /mnt/user-data/outputs 2>/dev/null || true

export PYTHONPATH="${DEERFLOW_BACKEND}:${DEERFLOW_BACKEND}/packages/harness:${OVERLAY_BACKEND}:${PYTHONPATH:-}"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

[[ -f "${REPO_ROOT}/.env" ]] && set -a && source "${REPO_ROOT}/.env" && set +a

echo "=== archon-deerflow dev server ==="
echo "  Repo:        ${REPO_ROOT}"
echo "  DeerFlow:    ${DEERFLOW_HOME}"

if $FULL_STACK; then
    # ── Build frontend if needed ──
    if [[ ! -d "${DEERFLOW_FRONTEND}/.next" ]]; then
        echo "[dev] Building frontend..."
        cd "${DEERFLOW_FRONTEND}"
        corepack enable && corepack install -g pnpm@10
        pnpm install --frozen-lockfile
        SKIP_ENV_VALIDATION=1 pnpm build
        cd "${REPO_ROOT}"
    fi

    # ── Stop any previous instances ──
    pkill -f "uvicorn app.gateway" 2>/dev/null || true
    pkill -f "pnpm start" 2>/dev/null || true
    pkill -f "nginx.*archon" 2>/dev/null || true
    sleep 1

    # ── Start Gateway (background) ──
    echo "[gateway] Starting on :${PORT} ..."
    cd "${DEERFLOW_BACKEND}"
    python3 -m uvicorn app.gateway.app:app --host 127.0.0.1 --port "${PORT}" &
    GATEWAY_PID=$!

    # ── Start Frontend (background) ──
    echo "[frontend] Starting on :${FRONTEND_PORT} ..."
    cd "${DEERFLOW_FRONTEND}"
    BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET:-dev-secret}" \
      DEER_FLOW_INTERNAL_GATEWAY_BASE_URL="http://127.0.0.1:${PORT}" \
      pnpm start &
    FRONTEND_PID=$!

    # ── Start nginx (foreground) ──
    echo "[nginx] Starting on :${NGINX_PORT} ..."
    cd "${REPO_ROOT}"
    # Rewrite nginx upstreams to localhost for non-Docker env
    sed -e 's/gateway:8001/127.0.0.1:'"${PORT}"'/' \
        -e 's/frontend:3000/127.0.0.1:'"${FRONTEND_PORT}"'/' \
        docker/nginx/nginx.conf > /tmp/archon-deerflow-nginx.conf

    echo "=================================="
    echo "  Gateway:   http://localhost:${PORT}"
    echo "  Frontend:  http://localhost:${FRONTEND_PORT}"
    echo "  nginx:     http://localhost:${NGINX_PORT}   ← 统一入口"
    echo "  Health:    http://localhost:${NGINX_PORT}/health"
    echo "=================================="

    # Trap to clean up background processes
    trap "kill ${GATEWAY_PID} ${FRONTEND_PID} 2>/dev/null; rm -f /tmp/archon-deerflow-nginx.conf" EXIT

    nginx -c /tmp/archon-deerflow-nginx.conf &
    NGINX_PID=$!
    wait ${NGINX_PID}
else
    # ── Gateway only ──
    cd "${DEERFLOW_BACKEND}"
    echo "  Listen:      http://localhost:${PORT}"
    echo "  Health:      http://localhost:${PORT}/health"
    echo "=================================="
    exec python3 -m uvicorn app.gateway.app:app \
        --host 0.0.0.0 --port "${PORT}" \
        --reload --reload-dir "${DEERFLOW_BACKEND}/app" --reload-dir "${OVERLAY_BACKEND}"
fi
