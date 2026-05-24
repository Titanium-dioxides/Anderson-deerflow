# ── archon-deerflow gateway ──
# DeerFlow is cloned from GitHub at build time. This project only provides
# the overlay layer (workflows, skills, configs).
#
# Build args:
#   DEER_FLOW_REPO  — upstream deer-flow repo (default: bytedance/deer-flow)
#   DEER_FLOW_REF   — branch or tag (default: main)
#   APT_MIRROR      — optional Debian mirror
# ────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim-bookworm

ARG APT_MIRROR
ARG DEER_FLOW_REPO=https://github.com/bytedance/deer-flow.git
ARG DEER_FLOW_REF=main

# ── System dependencies ──
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    fi \
    && apt-get update && apt-get install -y \
        curl git bash build-essential ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/*

# ── Lean 4 toolchain (elan) ──
# GitHub raw may be unstable in some build environments.
# If elan fails, Lean tools will report "lean not installed" gracefully.
RUN (curl --retry 3 --retry-delay 5 --http1.1 -sSf \
      https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
      || wget -qO- https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
      || wget -qO- https://cdn.jsdelivr.net/gh/leanprover/elan@master/elan-init.sh) \
    2>/dev/null | sh -s -- --default-toolchain leanprover/lean4:stable -y 2>/dev/null; \
    echo "Lean toolchain: $(ls /root/.elan/bin/ 2>/dev/null || echo 'unavailable — install elan manually')"
ENV PATH="/root/.elan/bin:$PATH"

WORKDIR /app/deer-flow

# ── Clone deer-flow from GitHub ──
RUN echo "Cloning deer-flow ${DEER_FLOW_REPO} @ ${DEER_FLOW_REF}" \
    && git clone --depth 1 --branch "${DEER_FLOW_REF}" "${DEER_FLOW_REPO}" /tmp/deer-flow-src \
    && cp -r /tmp/deer-flow-src/backend . \
    && cp -r /tmp/deer-flow-src/skills . 2>/dev/null || true \
    && cp /tmp/deer-flow-src/extensions_config.json . 2>/dev/null || true \
    && rm -rf /tmp/deer-flow-src

# ── Install deerflow-harness + Python dependencies (no uv) ──
RUN pip install \
    fastapi>=0.115.0 uvicorn[standard]>=0.34.0 \
    httpx>=0.28.0 python-multipart>=0.0.27 sse-starlette>=2.1.0 \
    langgraph>=0.2.0 langgraph-checkpoint-sqlite langgraph-sdk>=0.1.51 \
    langchain langchain-core langchain-deepseek \
    lark-oapi>=1.4.0 slack-sdk>=3.33.0 python-telegram-bot>=21.0 \
    markdown-to-mrkdwn>=0.3.1 email-validator>=2.0.0 bcrypt>=4.0.0 pyjwt>=2.9.0 \
    ddgs \
    && pip install -e /app/deer-flow/backend/packages/harness

# ── Layer archon-deerflow overlay on top ──
COPY skills ./skills
COPY extensions_config.json ./extensions_config.json
COPY config.yaml ./config.yaml
COPY overlay ./overlay

# ── Register our Phase 1-6 graphs ──
COPY overlay/backend/langgraph.json ./backend/langgraph.json

ENV PYTHONPATH=/app/deer-flow/backend/packages/harness:/app/deer-flow/overlay/backend:$PYTHONPATH
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
