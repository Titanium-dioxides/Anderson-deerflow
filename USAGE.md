# USAGE.md — 使用指南

## 项目简介

Archon-DeerFlow 是一个**自动化数学定理证明系统**：你给出一个自然语言描述的数学命题，系统经过六阶段流水线产出通过 Lean 4 编译检查的形式化证明。

内部集成了两篇论文的核心编排：

- **Rethlas** — 双代理（Generation + Verification）非形式化证明生成，10 通道 problem memory，迭代修复循环
- **Archon** — 三代理（Plan + Proving + Review）Lean 4 形式化证明循环，`.archon/` 状态目录合同

---

## 整体流程（From 命题 To 证明）

### Step 1 — 你给出一个命题

命题用自然语言描述即可，不需要任何 Lean 语法知识。例如：

> "Prove that the sum of the first n natural numbers equals n(n+1)/2."

或者中文：

> "证明：对于任意正整数 n，前 n 个自然数的和等于 n(n+1)/2。"

### Step 2 — 系统开始六阶段处理

```
你的命题（自然语言）
  │
  ▼
Phase 1: Runtime Bootstrap
  - 创建隔离的 thread 工作目录
  - 初始化 SQLite checkpointer（跨会话持久化）
  - 建立 journal / manifests / memory 等目录骨架
  ↓
Phase 2: Rethlas — 非形式化证明生成与验证
  - Generation Agent 用 LLM 生成候选证明
  - Verification Agent 验证正确性（correct / wrong）
  - 最多 20 轮修复循环：生成 → 验证 → 修复 → 重新验证
  - 期间使用 10 通道 memory 记录推理步骤、反例、搜索结果等
  - 产出：通过验证的非形式化证明文本
  ↓
Phase 3: Archon Scaffolding — 形式化骨架生成
  - 初始化 Lean 4 项目（lake init、lakefile、src/）
  - Auto-formalize agent 将非形式化证明转为 Lean 定理声明
  - 生成 .archon/ 状态目录（PROGRESS.md、task_done.md 等）
  - 此时 Lean 文件中包含 sorries（占位符），等待填充
  ↓
Phase 4: Archon Proving Loop — 形式化证明循环
  - Plan Agent：读取 .archon/ 状态，制定证明策略
  - Proving Agent(s)：并行填充 sorries，每个文件一个 agent
  - Review Agent：评估结果，决定重试或重新规划
  - 循环：最多 max_loops 轮 Plan → Prove → Review（默认 3 轮）
  - 产出：所有 sorries 已填充的 .lean 文件
  ↓
Phase 5: Polish / Export
  - 扫描剩余 sorry 和 axiom
  - lake build 编译检查
  - LLM 润色审查（警告、冗余、可提取引理）
  - 打包 .tar.gz artifact
  - 导出到 outputs/ 目录
  - 对齐跨阶段运行历史 → 生成最终 manifest
  ↓
Phase 6: E2E Acceptance（可选）
  - 7 个基准题目端到端验证
  - 每阶段边界不变量检查
  ↓
你的输出
  - 通过 Lean 4 编译的形式化证明
  - 可下载的 .tar.gz artifact
  - 完整的 runtime journal（每步可追溯）
```

### Step 3 — 你得到什么

| 产物 | 位置 | 说明 |
|---|---|---|
| 形式化证明（.lean 文件） | `outputs/{project}/` | 完整的 Lean 4 证明，可通过 `lake build` |
| 打包 artifact | `outputs/{project}/summary/` | `.tar.gz` 包，含所有源码 |
| Runtime journal | `workspace/{project}/journal/` | JSONL 日志，记录每阶段的时间戳和状态转换 |
| Manifests | `workspace/{project}/manifests/` | 每阶段 JSON manifest，含中间状态 |
| Rethlas memory | `workspace/{project}/memory/rethlas/` | 10 通道 JSONL，可审计推理过程 |
| Archon state | `workspace/{project}/formal/.archon/` | PROGRESS.md、task 状态、证明策略历史 |

---

## 快速开始

### Docker（推荐）

```bash
# 构建（自动从 GitHub 克隆 deer-flow runtime）
docker compose build

# 启动（三服务：nginx + frontend + gateway，监听 localhost:2026）
docker compose up -d

# 查看日志
docker compose logs -f gateway

# 停止
docker compose down
```

健康检查：`curl http://localhost:2026/health`

### 本地开发（无 Docker）

```bash
# 启动开发服务器（首次自动克隆 deer-flow，含热加载）
make dev

# 或指定端口
./scripts/dev.sh --port 9000
```

前提条件：Python 3.12+、`git`、Lean 4 工具链（可选，用于 `lake build`）

### 首次认证

```bash
# 1. 创建管理员
curl -s -X POST http://localhost:2026/api/v1/auth/initialize \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@local.dev","username":"admin","password":"admin123456","display_name":"Admin"}'

# 2. 登录（form data，username 填 email）
curl -s -X POST http://localhost:2026/api/v1/auth/login/local \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'username=admin@local.dev&password=admin123456' \
  -c ./cookies.txt

# 3. 后续请求携带 cookie
curl -s http://localhost:2026/api/models -b ./cookies.txt
```

---

## 提交命题（完整示例）

以下演示如何提交一个命题并拿到完整证明。你可以通过 Web UI 或 REST API 操作。

### 方式一：REST API（Python SDK）

```python
from overlay.backend.workflows import (
    run_phase1_workflow,
    run_phase2_rethlas_workflow,
    run_phase3_archon_scaffolding_workflow,
    run_phase4_archon_proving_workflow,
    run_phase5_polish_workflow,
)

thread_id = "my-thread-001"
project = "sum-of-naturals"
statement = "Prove that 1 + 2 + ... + n = n(n+1)/2 for all natural numbers n."

# Phase 1: 初始化 workspace
p1 = run_phase1_workflow(thread_id=thread_id, project_name=project)
print(f"Phase 1 done: {p1['stage']}")

# Phase 2: Rethlas 非形式化证明生成
p2 = run_phase2_rethlas_workflow(
    thread_id=thread_id,
    statement=statement,
    project_name=project,
    problem_id="sum-1-to-n",
)
print(f"Phase 2 verdict: {p2['verdict']}")

# Phase 3: 形式化骨架生成（传入 Phase 2 的非形式化证明）
p3 = run_phase3_archon_scaffolding_workflow(
    thread_id=thread_id,
    statement=statement,
    project_name=project,
    informal_proof_content=p2.get("candidate_proof", ""),
    candidate_proof_path=p2.get("verification_report_path", ""),
)
print(f"Phase 3 stage: {p3['stage']}")

# Phase 4: 形式化证明循环
p4 = run_phase4_archon_proving_workflow(
    thread_id=thread_id,
    statement=statement,
    project_name=project,
    max_loops=3,
    parallelism=2,
)
print(f"Phase 4 stage: {p4['stage']}, loops used: {p4.get('loop_count', 0)}")

# Phase 5: 润色与导出
p5 = run_phase5_polish_workflow(
    thread_id=thread_id,
    project_name=project,
)
print(f"Phase 5: compile_ok={p5['compile_ok']}, sorry_count={p5['sorry_count']}, export={p5['export_path']}")
```

### 方式二：REST API（curl）

Phase 之间通过 `runs/stream` 的 `stream_subgraphs: true` 可串联所有阶段。以下是最小示例——单独执行一个阶段：

```bash
# Phase 1: Bootstrap
curl -X POST http://localhost:2026/api/threads/my-thread/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "archon_deerflow_phase1",
    "input": {
      "thread_id": "my-thread",
      "project_name": "sum-of-naturals"
    },
    "config": {"configurable": {"thread_id": "my-thread"}}
  }'

# Phase 2: Rethlas
curl -X POST http://localhost:2026/api/threads/my-thread/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "archon_deerflow_phase2_rethlas",
    "input": {
      "thread_id": "my-thread",
      "statement": "Prove 1+2+...+n = n(n+1)/2",
      "project_name": "sum-of-naturals",
      "problem_id": "sum-1-to-n"
    },
    "config": {"configurable": {"thread_id": "my-thread"}}
  }'
```

### 方式三：Web UI

1. 浏览器打开 `http://localhost:2026`
2. 选择 assistant `archon_deerflow_phase1` → 输入参数 → 执行
3. 切换到 `archon_deerflow_phase2_rethlas` → 输入命题 → 执行
4. 依次完成 Phase 3、4、5
5. 在 outputs 页面下载 `.tar.gz` artifact

### 脚本方式：命令行工具

```bash
python3 scripts/prove.py \
  --thread my-thread-002 \
  --project "cauchy-schwarz" \
  --statement "Prove the Cauchy-Schwarz inequality for vectors in R^n." \
  --max-loops 5 \
  --parallelism 3
```

该脚本自动串联 Phase 1→5，输出最终证明路径和编译状态。

---

## 端到端基准测试

内置 7 个基准题目，`run_benchmark()` 自动遍历全部并生成通过/失败报告：

```python
from overlay.backend.workflows import run_benchmark

results = run_benchmark(thread_id="benchmark-run-1")
for r in results:
    print(f"{r['problem_id']} ({r['category']}): {'PASS' if r['all_checks_pass'] else 'FAIL'}")
```

题目分类：

| 类别 | 题目数 | 特征 |
|---|---|---|
| SIMPLE | 2 | 平凡定理，单文件，无需分解 |
| RETRIEVAL | 2 | 需要 mathlib 外部定理知识 |
| COMPLEX | 3 | 需要多引理分解 + 多轮证明 |

---

## 项目结构

```
archon-deerflow/                    ← 本项目（overlay only）
├── overlay/backend/workflows/     ← Phase 1-6 graph 定义
│   ├── phase1_runtime.py          ← Workspace bootstrap + checkpointer
│   ├── phase2_rethlas.py          ← Generation/Verification 双代理
│   ├── phase3_archon_scaffolding.py ← Auto-formalize + lake 初始化
│   ├── phase4_archon_proving.py   ← Plan/Prove/Review 三代理循环
│   ├── phase5_polish.py           ← sorry 扫描 + 编译 + 导出
│   ├── phase6_e2e.py              ← 端到端验收 + benchmark
│   └── rethlas_skill_tools.py     ← 10 个 Rethlas skill tools
├── overlay/backend/mcp/
│   └── lean_tools.py              ← 6 个 Lean CLI wrapper（@tool）
├── overlay/backend/langgraph.json ← Graph 注册
├── skills/                        ← 自定义 skills（archon-lean4 等）
├── config.yaml                    ← 模型/工具/sandbox 配置
├── docker/                        ← Dockerfile + nginx config
├── tests/                         ← 28 tests，覆盖 Phase 1-6
├── ARCHITECTURE_REPORT.md         ← 完整架构报告
└── USAGE.md                       ← 本文件
```

---

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | LLM API Key | 必填 |
| `TAVILY_API_KEY` | Web 搜索 API | 可选 |
| `JINA_API_KEY` | Web fetch API | 可选 |
| `ARCHON_MEMORY_URI` | SQLite checkpointer 路径 | 自动 `checkpoints.db` |
| `RETHLAS_MEMORY_ROOT` | Rethlas memory 根目录 | Phase 1 自动设置 |
| `RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK` | 允许直连外部 API | `false`（默认走 MCP） |
| `GATEWAY_LISTEN_HOST` | Gateway 监听地址 | `0.0.0.0` |
| `GATEWAY_LISTEN_PORT` | Gateway 监听端口 | `8001` |

### config.yaml（关键片段）

```yaml
models:
  - name: deepseek-v4
    use: langchain_deepseek:ChatDeepSeek
    model: deepseek-chat
    api_key: $DEEPSEEK_API_KEY
    max_tokens: 65536

tools:
  - name: lean_check_file
    use: overlay.backend.mcp.lean_tools:lean_check_file
    group: lean
  - name: lean_build
    use: overlay.backend.mcp.lean_tools:lean_build
    group: lean
  # ... 共 6 个 Lean 工具 + 4 个文件工具 + 2 个 web 工具
```

---

## Phase 参数速查

### Phase 1: `run_phase1_workflow`

| 参数 | 类型 | 说明 |
|---|---|---|
| `thread_id` | `str` | 线程 ID，隔离 workspace |
| `project_name` | `str` | 项目名，默认 `"project"` |

### Phase 2: `run_phase2_rethlas_workflow`

| 参数 | 类型 | 说明 |
|---|---|---|
| `thread_id` | `str` | 线程 ID |
| `statement` | `str` | 数学命题（自然语言） |
| `project_name` | `str` | 项目名 |
| `problem_id` | `str` | 问题 ID，用于 memory 隔离 |
| `max_attempts` | `int` | 最大修复次数，默认 20 |

### Phase 3: `run_phase3_archon_scaffolding_workflow`

| 参数 | 类型 | 说明 |
|---|---|---|
| `thread_id` | `str` | 线程 ID |
| `statement` | `str` | 数学命题 |
| `project_name` | `str` | 项目名 |
| `informal_proof_content` | `str` | Phase 2 产物：非形式化证明全文 |
| `candidate_proof_path` | `str` | Phase 2 产物：验证报告路径 |

### Phase 4: `run_phase4_archon_proving_workflow`

| 参数 | 类型 | 说明 |
|---|---|---|
| `thread_id` | `str` | 线程 ID |
| `statement` | `str` | 数学命题 |
| `project_name` | `str` | 项目名 |
| `max_loops` | `int` | 最大 Plan→Prove→Review 循环次数，默认 3 |
| `parallelism` | `int` | 并行 Proving Agent 数，默认 2 |

### Phase 5: `run_phase5_polish_workflow`

| 参数 | 类型 | 说明 |
|---|---|---|
| `thread_id` | `str` | 线程 ID |
| `project_name` | `str` | 项目名 |

### Phase 6: `run_e2e_workflow`

| 参数 | 类型 | 说明 |
|---|---|---|
| `thread_id` | `str` | 线程 ID |
| `statement` | `str` | 数学命题 |
| `project_name` | `str` | 项目名 |
| `problem_id` | `str` | 问题 ID |
| `category` | `str` | `SIMPLE` / `RETRIEVAL` / `COMPLEX` |
| `max_loops` | `int` | 最大证明循环次数 |
| `parallelism` | `int` | 并行 Lean Agent 数 |

---

## Workspace 布局

每次运行在 thread-scoped workspace 下创建：

```
{~/.deerflow_runtime | /mnt/user-data}/
├── uploads/                     ← 原始输入文件
├── workspace/{project}/
│   ├── references/              ← 参考资料（raw/ocr/structured）
│   ├── informal/                ← 非形式化证明
│   │   ├── proofs/              ← 候选证明文本
│   │   ├── verification/        ← 验证报告
│   │   ├── plans/               ← 证明计划
│   │   └── failures/            ← 失败记录
│   ├── formal/                  ← Lean 4 项目
│   │   ├── lakefile.lean
│   │   ├── lean-toolchain
│   │   ├── src/*.lean
│   │   └── .archon/             ← Archon 协调目录
│   │       ├── PROGRESS.md
│   │       ├── task_pending.md
│   │       ├── task_done.md
│   │       ├── USER_HINTS.md
│   │       ├── CURRENT_PLAN.md
│   │       ├── PROJECT_STATUS.md
│   │       └── task_results/*.md
│   ├── memory/
│   │   ├── rethlas/{problem}/   ← 10-channel Rethlas memory (*.jsonl)
│   │   └── archon/              ← attempt/review history (*.jsonl)
│   ├── journal/                 ← 跨阶段 JSONL 日志
│   ├── manifests/               ← 每阶段 JSON manifest
│   └── scratch/                 ← 临时文件（artifact .tar.gz）
└── outputs/                     ← 最终交付物
```

---

## 测试

```bash
make test                    # 28 tests
python3 -m pytest tests/ -q  # 同上
```

详见 [TESTING.md](TESTING.md)。

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE_REPORT.md](ARCHITECTURE_REPORT.md) | 完整架构报告：六阶段、信息流、文件布局、部署、测试 |
| [Principle.md](Principle.md) | 设计原则 |
| [KNOWLEDGE.md](KNOWLEDGE.md) | 开发过程中确认的关键知识 |
| [AUDIT.md](AUDIT.md) | 实现审计 |
| [TESTING.md](TESTING.md) | 测试说明 |
| [BLOCKERS.md](BLOCKERS.md) | 阻塞项记录 |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | 开发路线图 |
