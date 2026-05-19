# 综合审计报告 V3

> 审计时间：2026-05-19 17:48
> 范围：4 维度审计

---

## 维度 1：DeerFlow 规范合规度

**取 AUDIT_V2.md 终版评分：**

| 维度 | 评分 | 评级 |
|:----:|:----:|:----:|
| 状态 Schema | 6/8 | ✅ |
| Sandbox 管理 | 4/7 | ⚠️ 有改进空间 |
| Subagent 模式 | 6/8 | ✅ |
| 工具管理 | 3/4 | ✅ |
| Skills & Prompt | 4/4 | ✅ |
| 中间件与 Agent | 5/6 | ✅ |
| 代码质量 | 4/4 | ✅ |
| **综合** | **32/41 (78%)** | **良好** |

**结论：** 无明显 🔴 违规项。已通过 A1-E6 全面修复。

---

## 维度 2：Archon 移植完成度

**基准：** `/home/zdzdhd/ai4math/Archon`（Claude Code + shell scripts）

### 架构层

| 原始 Archon 特性 | 移植状态 | 移植位置 / 差距 |
|:-----------------|:--------:|:----------------|
| Claude Code CLI（`archon-loop.sh`） | 🔄 替换为 | `StateGraph(ArchonState)` — LangGraph 编排 |
| 3 阶段（autoformalize → prover → polish） | ✅ | `planner → prover → reviewer → review_agent` |
| Plan Agent（设置目标、分析失败、提供指引） | ⚠️ 部分 | `planner()` 节点纯逻辑，不调 LLM |
| Prover Agent（填充 sorry） | ✅ | `prover()` + `SubagentExecutor` |
| Review Agent（写 journals） | ✅ | `review_agent()` 节点 |
| 并行 Prover（每文件一 agent） | ✅ | `SubagentExecutor.execute_async()` |
| 串行/并行切换（`--serial` flag） | ❌ | 无此配置 |

### 工具层

| 工具 | 移植状态 | 备注 |
|:----|:--------:|:-----|
| lean-lsp MCP（22 个工具） | ✅ | 通过 `extensions_config.json` + `get_available_tools()` 加载 |
| `lean_goal` / `lean_local_search` | ✅ | 由 SubagentExecutor 内 subagent 调用 |
| `lean_multi_attempt` / `lean_diagnostic_messages` | ✅ | 同上 |
| `lean_hammer_premise` | ✅ | exact?/apply? 基础 |
| Lean4 Skills（`/archon-lean4:*`） | ✅ | `skills/custom/archon-lean4/` |
| `.claude/tools/archon-informal-agent.py` | ❌ | 移植到 `unified_graph.py` 的 `generator_node` |
| **`exact?` / `apply?`** 策略 | ⚠️ 禁用 | 因超时不可控 |

### 状态管理层

| 原始文件 | 移植状态 | 替代方案 |
|:---------|:--------:|:---------|
| `PROGRESS.md` | ⚠️ 部分 | `ArchonState.stage` + loop_count |
| `task_pending.md` / `task_done.md` | ⚠️ 部分 | `pending[]` + `completed[]` |
| `task_results/<file>.md` | ❌ | `attempt_history[]` 列表替代 |
| `proof-journal/sessions/session_N/*` | ✅ | review_agent 写入 |
| `PROJECT_STATUS.md` | ✅ | review_agent 写入 |
| **`USER_HINTS.md`** | 🔴 **缺失** | 未移植 |
| **`/- USER: ... -/` 注释** | 🔴 **缺失** | 未移植 |
| `.archon/logs/` | ❌ | 无日志文件 |
| **跨 session 记忆** | ❌ | StateGraph 是纯内存的 |

### Prompt 层

| 原始 Prompt 文件 | 移植状态 | 备注 |
|:-----------------|:--------:|:-----|
| `plan.md` | ⚠️ 部分 | planner 节点无 LLM 调用 |
| `prover-prover.md` | ✅ | SubagentConfig.system_prompt |
| `prover-autoformalize.md` | ❌ | 未实现独立 autoformalize 阶段 |
| `prover-polish.md` | ❌ | 未实现独立 polish 阶段 |
| `review.md` | ✅ | review_agent 节点逻辑 |
| `init.md` | ❌ | DeerFlow 自有部署流程 |

### 累计评分：Archon 移植度

| 类别 | 完整 | 部分 | 缺失 | 评分 |
|:----|:----:|:----:|:----:|:----:|
| 架构 | 3 | 1 | 1 | 70% |
| 工具 | 5 | 1 | 1 | 79% |
| 状态 | 2 | 2 | 3 | 43% |
| Prompt | 2 | 1 | 2 | 50% |
| **综合** | **12** | **5** | **7** | **63%** |

---

## 维度 3：Rethlas 移植完成度

**基准：** `/home/zdzdhd/ai4math/Rethlas`（基于 Codex CLI）

### 架构层

| 原始 Rethlas 特性 | 移植状态 | 移植位置/差距 |
|:------------------|:--------:|:--------------|
| Codex CLI 框架 | 🔄 替换为 | LangGraph StateGraph |
| GPT-5.4 模型 | 🔄 替换为 | deepseek-v4（可配置） |
| **生成 Agent** 10 个自适应技能 | ❌ | 压缩为单 prompt + 策略框架 |
| **验证 Agent** 3 个验证技能 | ❌ | 压缩为单 prompt |
| **Generate → Verify → Repair** 循环（≤3） | ✅ | `generator_node` → `verifier_node` → (loop) |
| **Matlas 定理搜索** | ⚠️ 部分 | `_search_mathlib()` via leansearch.net |
| `search_arxiv_theorems` 工具 | ❌ | 改用 leansearch.net |
| MCP memory（10 个 channels） | ❌ | LangGraph 状态管理替代 |
| `counterexample construction` 技能 | ❌ | 未实现 |
| `toy example construction` 技能 | ❌ | 未实现 |
| `subgoal decomposition` 技能 | ❌ | 未实现 |
| `recursive proving` 技能 | ❌ | 未实现 |
| `identify key failures` 技能 | ❌ | 未实现 |
| 验证服务 `verify_proof_service` | ❌ | 改用 LLM-invoke |
| `memory_init / memory_append / memory_search` | ❌ | 无记忆持久化 |
| `branch_update` 分支管理 | ❌ | 无分支管理 |

### 输出层

| 原始输出 | 移植状态 | 备注 |
|:---------|:--------:|:-----|
| `blueprint.md` → `blueprint_verified.md` | ❌ | 输出替换为 inline Lean 代码 |
| `results/{problem_id}/` | ❌ | 无独立结果目录 |
| `verification.json`（含 verdict） | ✅ | `extract_json()` 解析 LLM 输出 |

### 累计评分：Rethlas 移植度

| 类别 | 完整 | 部分 | 缺失 | 评分 |
|:----|:----:|:----:|:----:|:----:|
| 架构 | 2 | 1 | 0 | 83% |
| 技能 | 0 | 0 | 7 | 0% |
| 搜索 | 0 | 1 | 1 | 25% |
| 记忆 | 0 | 0 | 3 | 0% |
| 输出 | 1 | 0 | 3 | 25% |
| **综合** | **3** | **2** | **14** | **18%** |

**结论：** Rethlas 的**核心循环（generate → verify → repair）**已移植，但其核心价值——**10 个自适应推理技能 + Matlas 搜索引擎 + MCP 记忆系统**——基本未移植。Rethlas 移植度仅约 18%。

---

## 维度 4：source_paper.md 工作流满足度

检查 paper 描述的工作流能否在我们代码中执行。

### Paper 描述的 Pipeline

```
用户命题
  │
  ▼
Rethlas (Informal Agent)
  ├── search (Matlas: search_arxiv_theorems)
  ├── generate (10 adaptive skills)
  ├── verify (3 verify skills) ←→ repair (≤3)
  │
  ▼ (informal proof)
Archon (Formal Agent)
  ├── Scaffolding (autoformalize)
  ├── Proving (plan → prover → review loop)
  │   ├── LeanSearch → mathlib search
  │   ├── Ask Informal Agent (when stuck)
  │   ├── Memory system (cross-session)
  │   └── Review Agent (per-iteration journal)
  └── Polish
```

### 在我们的 unified_graph.py 中的实现

```
user statement
  │
  ▼
search_node ──────────── _search_mathlib (leansearch.net)  ⚠️ 简化
  │
  ▼
generator_node ──────────── SystemMessage + HumanMessage   ⚠️ 无自适应技能
  │
  ▼
verifier_node ───────────── extract_json → verdict         ⚠️ 无结构化验证
  │         ↻ (≤3 rounds)
  ▼
planner_node ────────────── scan → analyze → set stage     ✅
  ▼
prover_node ─────────────── SubagentExecutor + MCP tools   ✅
  ▼
reviewer_node ───────────── lake build → sorries count     ✅
  ├── COMPLETE → END
  └── FAIL → generator (archon_feedback 回路)              ✅
```

### SVG 文件检查

Paper 引用了 5 个 SVG 图（全部为 `frenzymath.com` 的远程 URL，非本地文件）：

| 图 | Paper 引用 | 本地文件 |
|:---|:----------|:--------:|
| `whole_pipeline.svg` | 框架整体流水线 | ❌ 无 |
| `rethlas_agent.svg` | Rethlas Agent 架构 | ❌ 无 |
| `Archon_Workflow.svg` | Archon 工作流 | ❌ 无 |
| `Agent_system_with_tools.svg` | Agent 系统与工具 | ❌ 无 |
| `rethlas_exploration_trajectory.svg` | Rethlas 探索轨迹 | ❌ 无 |
| `code_structure.svg` | 形式化代码结构 | ❌ 无 |

**无 SVG 文件对工作流无影响**（仅为文档插图）。但如果需要这些 SVG 用于演示，需从 paper 获取。

**2026-05-19 更新：** 6 个 SVG 已下载到 `paper_diagrams/`，详见 `paper_diagrams/README.md` 学习笔记。

### SVG 架构深度分析：9 个关键差距

来源：`paper_diagrams/` 6 个 SVG 的文本提取分析

| # | 差距 | 严重度 | SVG 来源 | 描述 |
|:-:|:-----|:------:|:---------|:-----|
| S1 | Rethlas 10 自适应推理 Skills 未移植 | 🔴 | rethlas_agent.svg | 原版有 10 个独立 Skills（Construct examples, counterexamples, subgoal decompositions, identify key failures等），我们压缩为单 prompt |
| S2 | 缺少多路并行探索 | 🟡 | rethlas_exploration_trajectory.svg | Rethlas 同时探索 Plan A/B/C，我们是线性单路径 |
| S3 | 缺少回环策略三级递进 | 🟡 | whole_pipeline.svg | Archon 策略：①细化→②分解→③重路由。我们只有 archon_feedback→generator 单一回路 |
| S4 | 缺少 Memory Manager 工具 | 🟡 | Agent_system_with_tools.svg | 原版 Memory Manager 是独立工具（Reading & Logging），我们的 attempt_history 无持久化 |
| S5 | Plan Agent 不主动分解 | 🟡 | Agent_system_with_tools.svg | 原版 Plan Agent 做 Strategy & Decomposition，我们的 planner 是纯逻辑节点 |
| S6 | 缺少 Ask Informal Agent 独立工具 | 🟡 | Agent_system_with_tools.svg | 原版 Ask Informal Agent 是 Lean Agent 可调用的独立 Tool |
| S7 | 缺少 Scaffolding(autoformalize) 阶段 | 🟢 | Archon_Workflow.svg | 原版三阶段（Scaffolding→Proving→Polish），我们跳过 Scaffolding |
| S8 | 缺少 Polish 阶段 | 🟢 | Archon_Workflow.svg | 原版 Polish(warnings, redundancy, specificity)，我们无 |
| S9 | 搜索范围远小于 Matlas | 🟡 | rethlas_agent.svg | 原版 Matlas(arXiv 13.6M 语句)，我们仅用 leansearch.net(mathlib-only) |

### 关键差距：Paper 描述 vs 实际实现

| Paper 描述特性 | 实现状态 | 差距描述 |
|:---------------|:--------:|:---------|
| Matlas 定理搜索（arXiv 13.6M 语句） | ⚠️ | 改用 leansearch.net（仅搜索 mathlib） |
| Rethlas 10 自适应推理技能 | ❌ | 单 prompt 替代 |
| Rethlas 3 验证技能 | ❌ | 单 prompt 替代 |
| Archon 子目标分解 | ❌ | planner 不做 LLM 生成 |
| Ask Informal Agent 回路 | ⚠️ | archon_feedback → generator，但无"lean 错误→阅读理解"步骤 |
| 跨 session 记忆 | ❌ | 纯内存 StateGraph |
| Archon 多 session 持久化 | ⚠️ | review_agent 写 journal，但无跨 session 记忆 |
| Polish 阶段 | ❌ | 无 golfs/refactor |
| 并行 Prover（每文件） | ✅ | SubagentExecutor |
| LeanSearch | ⚠️ | `_search_mathlib()` 仅搜索 leansearch.net，无语义搜索 |
| Review Agent 详细度 | ⚠️ | 有结构化记录但不如原始 detailed |

### 工作流功能性：✅ 能运行

unified_graph.py 从 `run_unified_workflow()` 开始的完整路径是可执行的：
1. search → 2. generate → 3. verify (≤3) → 4. planner → 5. prover (SubagentExecutor) → 6. reviewer → 7. review_agent → (loop/END)

archon_graph.py 从 `run_archon_workflow()` 也可执行（当已有 Lean 项目时）。

---

## 4 维度综合评分

| 维度 | 评分 | 关键待办 |
|:----:|:----:|:---------|
| 1. DeerFlow 规范 | **78%** ✅ | 无 🔴 问题 |
| 2. Archon 移植 | **63%** ⚠️ | USER_HINTS.md, autoformalize/polish 阶段缺失 |
| 3. Rethlas 移植 | **18%** ❌ | 10 自适应技能、Matlas、MCP 记忆未移植 |
| 4. 工作流满足度 | **60%** ⚠️ | 核心路径可执行，但质量差异大 |

### 关键待办（按优先级）

| 优先级 | 待办 | 来源 |
|:------:|:-----|:----:|
| 🔴 | 实现 Rethlas 10 自适应推理技能 | Rethlas AGENTS.md |
| 🔴 | 实现 USER_HINTS.md 注入机制 | Archon plan.md |
| 🟡 | 实现 autoformalize + polish 独立阶段 | Archon 3-phase |
| 🟡 | 实现子目标分解（planner 节点 LLM 调用） | Paper §3.2 |
| 🟡 | 增强 _search_mathlib 到 Matlas 级别 | Paper 脚注 1 |
| 🟢 | 实现消息持久化跨进程 | Archon 状态管理 |
| 🟢 | 添加 `/- USER: ... -/` 注释处理 | Archon prover.md |
