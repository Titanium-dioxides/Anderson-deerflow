#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# archon-deerflow local development server (no Docker)
#
# Prerequisites: Python 3.12+, uv, git
# Optional:       Lean 4 toolchain (elan) for lake build
#
# The script clones deer-flow from GitHub (if not already present) and
# runs the Gateway with our Phase 1-6 overlay registered.
#
# Usage:
#   ./scripts/dev.sh              # Start on port 8001 with hot reload
#   ./scripts/dev.sh --port 9000   # Custom port
#   ./scripts/dev.sh --no-clone    # Skip clone (deer-flow/ already exists)
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEER_FLOW_REPO="${DEER_FLOW_REPO:-https://github.com/bytedance/deer-flow.git}"
DEER_FLOW_REF="${DEER_FLOW_REF:-main}"
DEERFLOW_HOME="${REPO_ROOT}/deer-flow"
DEERFLOW_BACKEND="${DEERFLOW_HOME}/backend"
OVERLAY_BACKEND="${REPO_ROOT}/overlay/backend"

PORT="${GATEWAY_LISTEN_PORT:-8001}"
DO_CLONE=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --no-clone) DO_CLONE=false; shift ;;
        *) shift ;;
    esac
done

# ── Clone deer-flow from GitHub ──
if $DO_CLONE && [[ ! -d "${DEERFLOW_HOME}/backend" ]]; then
    echo "[dev] Cloning deer-flow from ${DEER_FLOW_REPO} @ ${DEER_FLOW_REF} ..."
    git clone --depth 1 --branch "${DEER_FLOW_REF}" "${DEER_FLOW_REPO}" "${DEERFLOW_HOME}"
    echo "[dev] deer-flow cloned."
elif [[ -d "${DEERFLOW_HOME}/backend" ]]; then
    echo "[dev] Using existing deer-flow at ${DEERFLOW_HOME}"
else
    echo "[dev] ERROR: deer-flow backend not found and --no-clone specified."
    exit 1
fi

cd "${DEERFLOW_BACKEND}"

# ── Register our overlay ──
cp "${OVERLAY_BACKEND}/langgraph.json" "${DEERFLOW_BACKEND}/langgraph.json"
echo "[dev] Registered Phase 1-6 graphs from overlay/backend/langgraph.json"

# ── Overlay configs ──
cp "${REPO_ROOT}/extensions_config.json" "${DEERFLOW_BACKEND}/extensions_config.json" 2>/dev/null || true
cp "${REPO_ROOT}/config.yaml" "${DEERFLOW_BACKEND}/config.yaml" 2>/dev/null || true

# ── Symlink skills ──
if [[ -d "${REPO_ROOT}/skills" ]]; then
    mkdir -p "${DEERFLOW_HOME}/skills"
    cp -r "${REPO_ROOT}/skills/"* "${DEERFLOW_HOME}/skills/" 2>/dev/null || true
fi

# ── Data directories ──
mkdir -p "${REPO_ROOT}/data/checkpoints"
mkdir -p /mnt/user-data/workspace /mnt/user-data/uploads /mnt/user-data/outputs 2>/dev/null || true

# ── Environment ──
export PYTHONPATH="${DEERFLOW_BACKEND}:${DEERFLOW_BACKEND}/packages/harness:${OVERLAY_BACKEND}:${PYTHONPATH:-}"
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    source "${REPO_ROOT}/.env"
    set +a
fi

echo "=== archon-deerflow dev server ==="
echo "  Repo:        ${REPO_ROOT}"
echo "  DeerFlow:    ${DEERFLOW_HOME} (source: ${DEER_FLOW_REPO})"
echo "  Overlay:     ${OVERLAY_BACKEND}"
echo "  Listen:      http://0.0.0.0:${PORT}"
echo "  Health:      http://localhost:${PORT}/health"
echo "=================================="

exec python3 -m uvicorn app.gateway.app:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --reload \
    --reload-dir "${DEERFLOW_BACKEND}/app" \
    --reload-dir "${OVERLAY_BACKEND}"
