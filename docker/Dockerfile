# ── Builder ──
FROM python:3.12-slim-bookworm AS builder

ARG UV_INDEX_URL=https://pypi.org/simple
ARG APT_MIRROR

RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    fi

RUN apt-get update && apt-get install -y \
    curl build-essential gnupg ca-certificates git \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# ── Install Lean 4 toolchain (elan) ──
RUN curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | \
    sh -s -- --default-toolchain leanprover/lean4:stable -y
ENV PATH="/root/.elan/bin:$PATH"

# ── Copy and install deer-flow backend ──
COPY deer-flow/backend ./deer-flow/backend
COPY deer-flow/pyproject.toml deer-flow/uv.lock ./deer-flow/

RUN --mount=type=cache,target=/root/.cache/uv \
    cd deer-flow && \
    UV_INDEX_URL=${UV_INDEX_URL} uv sync --extra sqlite

# ── Copy archon-deerflow overlay ──
COPY archon-deerflow/overlay ./deer-flow/overlay
COPY archon-deerflow/skills ./deer-flow/skills
COPY archon-deerflow/extensions_config.json ./deer-flow/extensions_config.json
COPY archon-deerflow/config.yaml ./deer-flow/config.yaml

# ── Copy DeerFlow skills + MCP ──
COPY deer-flow/skills ./deer-flow/skills
COPY deer-flow/extensions_config.json ./deer-flow/extensions_config.json

# ── Runtime ──
FROM python:3.12-slim-bookworm AS runtime

ARG APT_MIRROR

RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    fi

RUN apt-get update && apt-get install -y \
    curl git bash \
    && rm -rf /var/lib/apt/lists/*

# Lean 4 toolchain
COPY --from=builder /root/.elan /root/.elan
ENV PATH="/root/.elan/bin:$PATH"

# Python environment with deer-flow + deps
COPY --from=builder /app/deer-flow/.venv /app/deer-flow/.venv
COPY --from=builder /app/deer-flow /app/deer-flow
COPY --from=builder /root/.local/bin /root/.local/bin
ENV PATH="/root/.local/bin:$PATH"
ENV VIRTUAL_ENV=/app/deer-flow/.venv
ENV PATH="/app/deer-flow/.venv/bin:$PATH"

# ── SqliteSaver dependency ──
RUN uv pip install --no-cache langgraph-checkpoint-sqlite

WORKDIR /app/deer-flow
ENV PYTHONPATH=/app/deer-flow/backend/packages/harness:/app/deer-flow/overlay/backend:$PYTHONPATH
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8

COPY archon-deerflow/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
