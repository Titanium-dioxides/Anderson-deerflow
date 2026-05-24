# KNOWLEDGE.md

## 用途

记录开发过程中确认的重要知识，避免重复分析。

---

## K001 — 迁移的正确边界

- **结论**: 应保留论文中的算法结构，替换运行时基础设施。
- **含义**:
  - 论文 / 原实现决定 proof-domain workflow
  - DeerFlow 决定 runtime / tools / sandbox / workspace / subagents / history

## K002 — 最终目标不是单 agent

- **结论**: 不能把 Archon / Rethlas 压平成 DeerFlow 单 lead agent。
- **原因**:
  - Rethlas 需要 generation + verification 双代理闭环
  - Archon 需要 Plan Agent + Lean Agent + Review Agent

## K003 — Docker 语义决定文件结构

- **结论**: 证明项目应作为 DeerFlow thread-scoped workspace 项目运行。
- **路径语义**:
  - `/mnt/user-data/uploads`
  - `/mnt/user-data/workspace`
  - `/mnt/user-data/outputs`

## K004 — 双层 memory 必须保留

- **结论**:
  - DeerFlow memory 不替代 Rethlas/Archon 的 problem memory
  - 需要同时保留长期用户记忆与 problem-specific memory

## K005 — Review Agent 是核心能力

- **结论**: Review Agent 不是报告装饰层，而是下一轮策略的输入层。

## K006 — Phase 1 的最小代码落点

- **结论**: 新版代码骨架采用 `overlay/backend` 作为迁移实现层。
- **原因**:
  - 与现有 Dockerfile 路径一致
  - 可作为 DeerFlow backend 的附加 workflow 层
  - 便于后续逐步补齐 graph、workflows、runtime helpers

## K007 — Phase 1 的第一目标是 layout bootstrap

- **结论**: Phase 1 首个可验证目标不是 proving，而是 thread-scoped workspace layout。
- **当前实现**:
  - `overlay/backend/workflows/phase1_runtime.py`
  - 生成 `phase1_layout.json`
  - 对齐 `/mnt/user-data/{workspace,uploads,outputs}` 语义

## K008 — Phase 2 的第一目标是保住 Rethlas 结构

- **结论**: Phase 2 首先要恢复论文中的 generation/verification 双代理结构，而不是立即追求证明能力。
- **当前实现**:
  - `overlay/backend/workflows/phase2_rethlas.py`
  - `RETHLAS_SKILL_NAMES`
  - `RETHLAS_MEMORY_CHANNELS`
  - generation / verification graph nodes

## K009 — problem memory 先于真实推理能力落地

- **结论**: 在 Phase 2 中，先固定 Rethlas problem memory 目录和 channel 契约是合理的。
- **原因**:
  - 这是后续 skills、recursive proving、review 的共享数据底座
  - 能先把论文结构中的 memory discipline 固定下来

## K010 — Phase 2 的 runtime 接入应分两层

- **结论**: 先接通 generation / verification 的 DeerFlow agent runtime，再处理 recursive proving 的 subagent runtime。
- **原因**:
  - generation / verification 是论文结构最外层闭环
  - recursive proving 是二阶能力，可在主闭环稳定后接入

## K011 — 结构存在不等于论文能力已实现

- **结论**: workflow 节点、manifest、目录结构存在，只能证明迁移骨架已建立，不能自动推断论文级行为已落地。
- **含义**:
  - 测试需要区分“结构断言”和“能力断言”
  - `AUDIT.md` 中的状态必须反映真实运行行为，而不是只反映代码文件是否存在

## K012 — Rethlas memory 必须按 thread/problem scoped 读取和写入

- **结论**: `query_memory` 不能扫描整个 `.deerflow_runtime`，必须绑定当前 thread workspace 下的当前 problem memory。
- **原因**:
  - 否则会污染问题上下文
  - verification-triggered repair 无法可靠复用上一轮失败总结

## K013 — Phase 4 的 DeerFlow-native 化要区分“优先路径”和“真实主路径”

- **结论**: 仅提供 `task` tool fallback 或 `get_available_tools()` fallback 还不够，真正的主路径应由 DeerFlow subagent/tool aggregation 驱动。
- **当前状态**:
  - Lean tools 已优先尝试 `get_available_tools(groups=["lean"])`
  - Phase 4 已去掉本地线程池主导，改为 parent workflow 收集 subagent/task 结果

## K014 — 持久 checkpointer 与 runtime history 需要放在线程级 runtime 根目录

- **结论**: checkpointer 和 runtime event log 不应继续分散在各 phase manifest 里，而应放到 thread-scoped runtime 目录。
- **当前实现**:
  - `checkpoints/langgraph.sqlite` 作为优先持久 checkpointer 路径
  - `threads/<thread_id>/runtime/run_history.jsonl` 作为 thread runtime event log
  - Phase 5 从该 event log 读取并生成对齐报告

## K015 — Rethlas skills 自己就是 memory producer

- **结论**: problem memory 不应只由 workflow 节点事后补写，skill tools 本身也必须把结构化产物写回对应 channel。
- **当前实现**:
  - `obtain_immediate_conclusions` → `conclusions`
  - `search_mathematical_results` / `query_memory` → `search_results`
  - `construct_examples` / `construct_counterexamples` → `examples` / `counterexamples`
  - `propose_decomposition` / `direct_proving` / `recursive_proving` → `decompositions` / `proof_steps` / `recursive_results`
  - `identify_key_failures` / `verify_proof` → `failures` / `failed_paths` / `verifications`
