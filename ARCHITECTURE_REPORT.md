# ARCHITECTURE_REPORT.md — Archon-DeerFlow 架构报告

## 1. 概述

Archon-DeerFlow 是一个**自动化数学定理证明系统**，接收自然语言描述的数学命题，经过六阶段流水线产出通过编译检查的 Lean 4 证明。

项目将两篇论文（Archon 和 Rethlas）的 agent 编排逻辑整合到 DeerFlow（字节跳动）运行时之上：

- **Rethlas** — 双代理（Generation + Verification）非形式化证明生成与验证，10 通道 problem memory
- **Archon** — 三代理（Plan + Proving + Review）Lean 4 形式化证明循环，`.archon/` 状态目录合同

---

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 编排 | LangGraph `StateGraph` + `TypedDict` |
| LLM 后端 | DeepSeek Chat（可替换 OpenAI） |
| 证明语言 | Lean 4 + mathlib |
| 运行时 | DeerFlow (FastAPI gateway + Next.js UI) |
| 持久化 | SQLite checkpointer (LangGraph) |
| 部署 | Docker Compose (nginx + frontend + gateway) |

---

## 3. 六阶段流水线

### Phase 1 — Runtime Bootstrap
**文件:** [phase1_runtime.py](overlay/backend/workflows/phase1_runtime.py)

- 建立 thread-scoped 目录树（workspace、uploads、outputs、references、informal、formal、memory、journal、manifests、scratch）
- 选择 checkpointer：优先 SQLite（`ARCHON_MEMORY_URI`），fallback 到 `MemorySaver`
- 结构化 JSONL journal，记录阶段转换与时间戳

**State 阶段:** `BOOTSTRAP → READY`

### Phase 2 — Rethlas: Informal Proof Generation + Verification
**文件:** [phase2_rethlas.py](overlay/backend/workflows/phase2_rethlas.py)

- 初始化 10 通道 problem-scoped memory：`conclusions`, `examples`, `counterexamples`, `decompositions`, `proof_steps`, `failed_paths`, `verifications`, `recursive_results`, `search_results`, `failures`
- **Generation Agent**：LLM 生成非形式化候选证明，写入 memory channels
- **Verification Agent**：验证正确性，产出 `correct`/`wrong` 裁决 + 修复提示
- 修复循环：最多 `max_attempts` 轮生成-验证迭代

**10 个 Skill Tools（[rethlas_skill_tools.py](overlay/backend/workflows/rethlas_skill_tools.py)）:**
`query_memory`, `write_memory`, `search_math_results`, `construct_toy_examples`, `construct_counterexamples`, `recursive_proving`, `direct_proving`, `verify_proof`, `web_search`, `web_fetch`

**State 阶段:** `BOOTSTRAP → MEMORY_READY → GENERATED → VERIFIED → FAILED`

### Phase 3 — Archon Scaffolding: Auto-Formalization
**文件:** [phase3_archon_scaffolding.py](overlay/backend/workflows/phase3_archon_scaffolding.py)

- 桥接 Phase 2 输出，初始化 Lean 项目（`lake init`，创建 `Theorems.lean`、`Lemmas.lean`）
- 生成 Archon 状态目录（`.archon/`），包含 `PROGRESS.md`, `task_done.md`, `task_pending.md`, `USER_HINTS.md`
- Auto-formalize agent：LLM 驱动的自然语言到 Lean 转换，生成带 `sorry` 的形式化占位符
- 参考文献摄取与索引

**State 阶段:** `BOOTSTRAP → INGESTION → FORMAL_READY`

### Phase 4 — Archon Proving Loop
**文件:** [phase4_archon_proving.py](overlay/backend/workflows/phase4_archon_proving.py)

- 三代理循环：
  1. **Plan Agent** — 读取 Archon 状态文件，生成文件级证明策略
  2. **Proving Agent** — 对每个 module file 尝试填充 `sorry` 为完整证明
  3. **Review Agent** — 评估证明结果，更新策略，标记 blocked files
- 循环机制：最多 `max_loops` 轮 Plan → Prove → Review 迭代
- 跟踪 `pending/completed/blocked_files`、`attempt_history`、`review_history`

**State 阶段:** `PHASE3_SYNC → PLAN_READY → PROVING → REVIEWED → STRATEGY_READY → COMPLETE | FAILED`

### Phase 5 — Polish / Export
**文件:** [phase5_polish.py](overlay/backend/workflows/phase5_polish.py)

- sorry/axiom 扫描：检测所有 `.lean` 文件中剩余的未完成项
- 编译检查：`lake build`
- LLM 润色审查：发现警告、冗余、可提取引理
- 构建产物：`.tar.gz` 打包
- 导出到 `/mnt/user-data/outputs`
- 跨阶段运行时历史对齐 + 最终 manifest

**State 阶段:** `PHASE4_SYNC → SORRY_AXIOM_CHECKED → COMPILE_CHECKED → POLISHED → ARTIFACT_PACKED → EXPORTED → HISTORY_ALIGNED → MANIFEST_READY`

### Phase 6 — End-to-End Acceptance Testing
**文件:** [phase6_e2e.py](overlay/backend/workflows/phase6_e2e.py)

- 串联 Phase 1→5 作为单次端到端运行
- 7 个基准题目，3 个类别：
  - **SIMPLE** (2) — 平凡定理，单文件
  - **RETRIEVAL** (2) — 需要 mathlib 外部知识
  - **COMPLEX** (3) — 需要多引理分解与多轮证明
- 每阶段边界进行结构和行为不变量验证

**State 阶段:** `INIT → PHASE1_DONE → … → PHASE5_DONE → VERIFIED`

---

## 4. 跨阶段信息流

```
Phase 1 ──(workspace paths)──> Phase 2
Phase 2 ──(statement, rethlas output)──> Phase 3
Phase 3 ──(lean project, archon state, modules)──> Phase 4
Phase 4 ──(pending/completed/blocked, history, plan)──> Phase 5
Phase 5 ──(sorry_count, compile_ok, artifacts, export)──> Phase 6
```

每个阶段通过从上一阶段的 state dict 中复制字段传递信息（LangGraph `TypedDict` + node 函数参数），而非共享一个全局 state 类。

---

## 5. 文件系统布局

Phase 1 的 `bootstrap_layout()` 创建以下结构：

```
{workspace_root}/
  {project_name}/
    uploads/          # 用户上传的参考文件
    outputs/          # 最终 artifact 输出
    references/       # 已摄取的参考文献（结构化 JSON）
    informal/         # Phase 2 非形式化证明输出
    formal/           # Phase 3/4 Lean .lean 文件 + lake 项目
    memory/           # Phase 2-4 agent memory（JSONL channels）
    journal/          # Runtime event log（JSONL）
    manifests/        # 每阶段 manifest（JSON）
    scratch/          # 临时工作文件
```

---

## 6. 关键架构决策

1. **LangGraph-native**：所有阶段是编译后的 `StateGraph`，具有独立的 `TypedDict` state、显式节点函数和条件边
2. **双层 memory**：DeerFlow 长期用户记忆 + Rethlas/Archon problem-specific 10 通道 memory，互不替代
3. **Review Agent 是策略输入层**：不只是报告装饰器——Review Agent 的输出驱动 Plan Agent 的下一轮策略
4. **Lean 工具链封装**：所有 Lean 交互通过 `@tool` 装饰器封装（[lean_tools.py](overlay/backend/mcp/lean_tools.py)），返回结构化 JSON 结果
5. **持久 checkpointer**：优先 SQLite（跨会话持久化），配置了 `ARCHON_MEMORY_URI` 即自动切换；runtime event log 位于 `threads/<thread_id>/runtime/run_history.jsonl`

---

## 7. 部署架构

```
                    Port 2026
                       │
                   ┌───▼───┐
                   │ nginx │  (reverse proxy)
                   └─┬───┬─┘
                     │   │
            ┌────────▼┐  └────────────┐
            │frontend │  Next.js UI   │
            └─────────┘               │
                              ┌───────▼──────┐
                              │   gateway    │  FastAPI + LangGraph
                              │  (port 8001) │
                              └──────────────┘
```

**服务间通信:** `frontend → gateway:8001` (internal docker network)

**挂载点:**
- `data/` — 持久 storage
- `workspace/` — thread-scoped 工作空间
- `uploads/` — 用户上传文件
- `outputs/` — 导出 artifacts
- `overlay/`, `skills/`, `config.yaml` — 开发时只读挂载

---

## 8. 测试覆盖（28 tests）

| 测试文件 | 覆盖范围 |
|---|---|
| [test_phase1_runtime.py](tests/test_phase1_runtime.py) | SQLite checkpointer, runtime event logging |
| [test_phase2_rethlas.py](tests/test_phase2_rethlas.py) | Repair loop, memory channels, env requirements, web fallback, MCP-only mode |
| [test_phase3_archon_scaffolding.py](tests/test_phase3_archon_scaffolding.py) | Archon layout generation, fallback module validity |
| [test_phase4_archon_proving.py](tests/test_phase4_archon_proving.py) | Proving loop attempts/completion, failure on dead loop, subagent preference |
| [test_phase5_polish.py](tests/test_phase5_polish.py) | Full pipeline completion, Phase 4 failure handling, sorry/axiom detection, compile checks, polish review, artifact export, history alignment |
| [test_phase6_e2e.py](tests/test_phase6_e2e.py) | SIMPLE/RETRIEVAL/COMPLEX benchmarks, stage invariants, category-structure match |

---

## 9. Rethlas Memory Channels（每问题专用）

| Channel | 写入方 | 用途 |
|---|---|---|
| `conclusions` | `obtain_immediate_conclusions` | 即时结论 |
| `examples` | `construct_toy_examples` | 构造示例 |
| `counterexamples` | `construct_counterexamples` | 反例 |
| `decompositions` | `propose_subgoal_decomposition` | 子目标分解 |
| `proof_steps` | `direct_proving` | 证明步骤 |
| `failed_paths` | `identify_key_failures` | 失败路径 |
| `verifications` | `verify_proof` | 验证结果 |
| `recursive_results` | `recursive_proving` | 递归证明结果 |
| `search_results` | `search_math_results`, `query_memory` | 搜索结果 |
| `failures` | `identify_key_failures` | 关键失败 |
