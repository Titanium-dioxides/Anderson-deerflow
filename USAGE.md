# USAGE.md — 使用指南

Archon-DeerFlow 是一个**自动化数学定理证明系统**：输入自然语言命题，输出 Lean 4 形式化证明。

---

## 部署方式

### 方式一：本机部署（无 Docker）

本机部署同样运行三服务栈（nginx + 前端 + gateway），与 Docker 模式架构完全一致。

**前提：** Python 3.12+ / Node.js 22+ / pnpm / git / nginx

```bash
# 1. 克隆项目
git clone https://github.com/Titanium-dioxides/Anderson-deerflow.git
cd Anderson-deerflow

# 2. 创建 Python 虚拟环境
python3.12 -m venv .venv && source .venv/bin/activate

# 3. 安装 Python 依赖
pip install fastapi uvicorn[standard] httpx python-multipart sse-starlette \
  langgraph langgraph-checkpoint-sqlite langgraph-sdk \
  langchain langchain-core langchain-deepseek \
  lark-oapi slack-sdk python-telegram-bot markdown-to-mrkdwn \
  email-validator bcrypt pyjwt ddgs

# 4. 克隆 deer-flow runtime + 安装 harness
git clone --depth 1 --branch main \
  https://github.com/bytedance/deer-flow.git deer-flow
pip install -e deer-flow/backend/packages/harness

# 5. 构建前端（Next.js）
cd deer-flow/frontend
corepack enable && corepack install -g pnpm@10
pnpm install --frozen-lockfile
SKIP_ENV_VALIDATION=1 pnpm build
cd ../..

# 6. 安装 Lean 4（可选，lake build 需要）
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
  | sh -s -- --default-toolchain leanprover/lean4:stable -y
export PATH="$HOME/.elan/bin:$PATH"

# 7. 配置
cp .env.example .env && cp config.example.yaml config.yaml
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxx

# 8. 部署 overlay 到 deer-flow
cp overlay/backend/langgraph.json deer-flow/backend/langgraph.json
cp -r overlay/backend deer-flow/overlay/backend
cp -r skills deer-flow/skills
cp config.yaml deer-flow/backend/config.yaml
cp extensions_config.json deer-flow/backend/extensions_config.json

# 9. 启动 Gateway（终端 1）
cd deer-flow/backend
PYTHONPATH=".:packages/harness:../../overlay/backend" \
  python3 -m uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001

# 10. 启动前端（终端 2）
cd deer-flow/frontend
pnpm start  # 监听 http://localhost:3000

# 11. 启动 nginx（终端 3）
nginx -c "$(pwd)/docker/nginx/nginx.conf"  # 监听 http://localhost:2026
```

**或一键启动：**
```bash
./scripts/dev.sh             # 自动 clone + 启动 Gateway + 热加载（仅 gateway）
./scripts/dev.sh --full      # 三服务全栈启动
```

Gateway → `:8001` / 前端 → `:3000` / nginx 统一入口 → `:2026`。

### 方式二：Docker 部署

```bash
# Gateway 模式（完整三服务栈：nginx + 前端 + gateway）
docker compose up -d           # 监听 http://localhost:2026

# Studio 模式（仅 graph 可视化）
docker compose -f docker-compose.studio.yml up -d  # 监听 http://localhost:8123
```

### 反向代理架构（Docker）

```
浏览器 → :2026 (nginx)
              │
              ├─ /api/*          → gateway:8001   (FastAPI + LangGraph agent)
              ├─ /health         → gateway:8001   (健康检查)
              ├─ /docs           → gateway:8001   (Swagger)
              ├─ /openapi.json   → gateway:8001   (OpenAPI schema)
              └─ /* (其他)       → frontend:3000  (Next.js Web UI)
```

| 路由 | 后端 | 说明 |
|------|------|------|
| `/api/*` | gateway:8001 | 所有 REST API + LangGraph agent 调用 |
| `/health` | gateway:8001 | 健康检查 `{"status":"healthy"}` |
| `/docs`, `/openapi.json` | gateway:8001 | Swagger UI 和 OpenAPI schema |
| `/` 及其他所有路径 | frontend:3000 | Next.js 页面（聊天、设置、agent 管理） |

关键细节：
- **流式响应**：`proxy_buffering off` + `chunked_transfer_encoding on`，LLM SSE 输出实时到达
- **超时**：`proxy_read_timeout 600s`，长证明任务不会因代理超时中断
- **服务发现**：`set $gateway_upstream gateway:8001` 每次请求解析 Docker DNS，容器重启后 IP 变化无需重启 nginx
- **WebSocket**：前端路由配置了 `Upgrade` / `Connection` 头，支持 Next.js HMR

本机部署不经过 nginx，Gateway 直接监听 `:8001`。

### 首次认证

```bash
curl -s -X POST http://localhost:8001/api/v1/auth/initialize \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@local.dev","username":"admin","password":"admin123456","display_name":"Admin"}'

curl -s -X POST http://localhost:8001/api/v1/auth/login/local \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'username=admin@local.dev&password=admin123456' \
  -c ./cookies.txt
```

---

## 使用方式

### 命令行（推荐）

```bash
# 直接给命题
python3 scripts/prove.py "Prove that 1+2+...+n = n(n+1)/2 for all natural numbers n."

# 从文件读
python3 scripts/prove.py -f problem.txt

# 指定类别和参数
python3 scripts/prove.py -f problem.txt -c RETRIEVAL --max-loops 5 -o ./output

# 安静模式（只输出 JSON）
python3 scripts/prove.py "1+1=2" -q
```

产物在 `-o` 指定的目录（默认 `workspace/<项目名>/`）：
```
informal_proof.md          ← 非形式化证明
formal/src/*.lean           ← Lean 4 形式化证明
report.json                 ← 完整运行报告
```

### Python SDK

```python
import sys; sys.path.insert(0, "overlay/backend")
from workflows import run_e2e_workflow

result = run_e2e_workflow(
    thread_id="my-thread",
    statement="Prove that there are infinitely many primes.",
    project_name="prime-proof",
    category="RETRIEVAL",
    max_loops=5,
)
print(result["all_checks_pass"])  # True
```

### 逐阶段调用

```python
from workflows import (
    run_phase1_workflow,           # workspace bootstrap
    run_phase2_rethlas_workflow,   # informal proof
    run_phase3_archon_scaffolding_workflow,  # Lean scaffold
    run_phase4_archon_proving_workflow,      # proving loop
    run_phase5_polish_workflow,    # polish/export
)

p1 = run_phase1_workflow("tid", "project")
p2 = run_phase2_rethlas_workflow("tid", "theorem statement", "project", "problem")
p3 = run_phase3_archon_scaffolding_workflow("tid", "statement", "project",
      informal_proof_content=p2.get("informal_proof", ""))
p4 = run_phase4_archon_proving_workflow("tid", "statement", "project", max_loops=5)
p5 = run_phase5_polish_workflow("tid", "project")
```

### Web UI

1. 打开 `http://localhost:2026`（Docker）或 `http://localhost:8001`（本机）
2. 选择 agent（如 `archon-deerflow-phase6-e2e`）
3. 输入命题，开始对话

### REST API

```bash
curl -X POST http://localhost:8001/api/threads/{tid}/runs/stream \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "assistant_id": "archon-deerflow-phase6-e2e",
    "input": {
      "thread_id": "...",
      "statement": "Prove that 1+1=2.",
      "project_name": "test",
      "category": "SIMPLE",
      "max_loops": 3
    },
    "config": {"configurable": {"thread_id": "..."}}
  }'
```

---

## 六阶段流水线

```
命题（自然语言）
  │
  ▼
Phase 1 — Workspace Bootstrap
  thread 隔离目录 / checkpointer / journal / manifests / memory
  ↓
Phase 2 — Rethlas 非形式化证明
  Generation Agent (10 skills) → Verification Agent → repair loop
  定理搜索: Mathlib + Matlas + Loogle + LeanSearch + Web
  ↓
Phase 3 — Archon Scaffolding
  Lean 项目初始化 (lake) → autoformalize → .lean skeleton (含 sorry)
  ↓
Phase 4 — Archon Proving Loop
  Plan → Parallel Lean Agents (LSP tools) → Reviewer → Review Agent → loop
  ↓
Phase 5 — Polish & Export
  sorry/axiom scan → lake build → polish → artifact.tar.gz → export
  ↓
Phase 6 — E2E Acceptance（可选）
  结构化基准题 + 全阶段不变量检查
```

---

## 可用 Agent

| Assistant ID | 功能 |
|------|------|
| `archon-deerflow-phase1` | workspace 初始化 |
| `archon-deerflow-phase2-rethlas` | 非形式化证明生成 |
| `archon-deerflow-phase3-archon-scaffolding` | Lean 骨架生成 |
| `archon-deerflow-phase4-archon-proving` | 形式化证明循环 |
| `archon-deerflow-phase5-polish` | 最终检查和导出 |
| `archon-deerflow-phase6-e2e` | 全流程串联（推荐） |

---

## 配置

### 环境变量

| 变量 | 说明 | 必填 |
|------|------|:--:|
| `DEEPSEEK_API_KEY` | LLM API Key | ✅ |
| `TAVILY_API_KEY` | Web 搜索增强 | — |
| `SERPER_API_KEY` | Google 搜索 | — |
| `JINA_API_KEY` | 网页内容提取 | — |
| `ARCHON_DEERFLOW_RUNTIME_ROOT` | 运行时根目录 | 默认 `.deerflow_runtime` |

### 搜索渠道（免费可用）

| 渠道 | 说明 |
|------|------|
| Mathlib 本地（ripgrep）| Lean 定理声明名/类型/全文搜索 |
| Loogle API | Lean 类型模式搜索 |
| LeanSearch API | 自然语言→定理语义搜索 |
| Matlas API | 数学文献定理搜索（论文/书籍） |
| DuckDuckGo | Web 通用搜索回退 |

---

## Phase 参数速查

| 函数 | 关键参数 |
|------|---------|
| `run_phase1_workflow` | `thread_id`, `project_name` |
| `run_phase2_rethlas_workflow` | `thread_id`, `statement`, `project_name`, `problem_id` |
| `run_phase3_archon_scaffolding_workflow` | `thread_id`, `statement`, `project_name`, `informal_proof_content` |
| `run_phase4_archon_proving_workflow` | `thread_id`, `statement`, `project_name`, `max_loops`(3), `parallelism`(2) |
| `run_phase5_polish_workflow` | `thread_id`, `project_name` |
| `run_e2e_workflow` | `thread_id`, `statement`, `project_name`, `category`, `max_loops`, `parallelism` |

---

## Workspace 布局

```
.deerflow_runtime/threads/{tid}/user-data/
├── uploads/
├── workspace/{project}/
│   ├── references/              ← 参考资料
│   ├── informal/                ← 非形式化证明
│   │   ├── proofs/              ← 候选人证明
│   │   ├── verification/        ← 验证报告
│   │   ├── plans/               ← 证明计划
│   │   └── failures/            ← 失败记录
│   ├── formal/                  ← Lean 4 项目
│   │   ├── lakefile.lean
│   │   ├── lean-toolchain
│   │   ├── src/*.lean
│   │   └── .archon/             ← Archon 协调目录
│   ├── memory/
│   │   ├── rethlas/{problem}/   ← 10-channel Rethlas memory
│   │   └── archon/              ← attempt/review history
│   ├── journal/
│   ├── manifests/               ← 每阶段 JSON manifest
│   └── scratch/                 ← artifact.tar.gz
└── outputs/                     ← 最终交付物
```

---

## 测试

```bash
python3 -m pytest tests/ -q     # 28 项测试
```

---

## 项目文件结构

```
archon-deerflow/
├── overlay/backend/             ← 本项目的全部代码（overlay only）
│   ├── workflows/               ← Phase 1-6 graph 定义
│   └── mcp/                     ← Lean LSP 工具（6 + search/verify）
├── skills/                      ← 自定义 skills（math-prover）
├── agents/                      ← 6 个 agent 定义（Web UI 可见）
├── docker/                      ← Dockerfile + nginx + entrypoint
├── tests/                       ← 28 项测试
├── scripts/                     ← prove.py + dev.sh + graph_viz.py
├── config.example.yaml          ← 配置模板（复制为 config.yaml）
├── .env.example                 ← 环境变量模板（复制为 .env）
├── docker-compose.yml           ← Gateway 模式（nginx+前端+gateway）
└── docker-compose.studio.yml    ← Studio 模式（图可视化）
```

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [TESTING.md](TESTING.md) | 测试架构与用例覆盖 |
| [AUDIT.md](AUDIT.md) | 论文→原实现→新实现对齐表 |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | 六阶段开发路线 |
| [DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md](DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md) | 迁移规范 |
