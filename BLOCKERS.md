# BLOCKERS.md

## 说明

本文件只记录两类内容：

1. **真正的 blocker**
   - 外部依赖缺失
   - 环境/部署限制
   - 架构级约束
2. **已解除的 blocker 历史**

未实现但不构成阻塞的项，放入 `TODO.md`。

---

## 当前 Blockers

### B-006 DeerFlow runtime 持久 history / checkpointer 尚未真正接线

- **状态**: resolved
- **范围**: Phase 1 / Phase 5 runtime integration
- **说明**: `phase1_runtime.py` 现已优先使用 `SqliteSaver` 持久 checkpointer，并建立 thread-scoped `runtime/run_history.jsonl`；`phase5_polish.py` 改为读取该 runtime event log 做 history alignment。
- **解除时间**: 2026-05-24

### B-001 外部原始代码对齐尚未完成

- **状态**: resolved
- **范围**: Rethlas / Archon 编排完全对齐
- **说明**: 对齐表已完成 → `AUDIT.md`。覆盖 Rethlas 12 项、Archon 9 项、三阶段 3 项、基础设施 10 项、搜索可信度 6 项、端到端 5 项。
- **解除时间**: 2026-05-24

### B-002 DeerFlow-native 重构尚未开始

- **状态**: resolved
- **范围**: workflow runtime
- **说明**: Phase 1 已启动，最小 runtime skeleton 已落地到 `overlay/backend/workflows/phase1_runtime.py`。
- **解除时间**: 2026-05-22

### B-003 DeerFlow Gateway 路径尚未接通新 workflow

- **状态**: resolved
- **范围**: Phase 1 runtime integration
- **说明**: 所有 graph 已注册到 `langgraph.json`；Python SDK 调用全流程验证通过（Cauchy-Schwarz 等）；Gateway REST API 连通性验证通过（health/models/list）；`scripts/prove.py` 命令行工具可用。
- **解除时间**: 2026-05-24

### B-004 Phase 2 仍为结构骨架，未接 DeerFlow agent runtime

- **状态**: resolved
- **范围**: Rethlas generation / verification
- **说明**: Phase 2 的 generation / verification 已切到 DeerFlow agent runtime，并建立了最小 skill tool 暴露层。
- **解除时间**: 2026-05-22

### B-005 Phase 2 缺少 recursive proving 的 DeerFlow subagent runtime

- **状态**: resolved
- **范围**: Rethlas recursive exploration
- **说明**: `recursive_proving` tool 已生成结构化 subagent prompts；`_run_deerflow_agent` 支持 `subagent_enabled=True` → `RuntimeFeatures(subagent=True)` 注入 `task` tool。Phase 2 generation agent 已启用 subagent 并行探索。
- **解除时间**: 2026-05-24

---

## 已解除 Blockers

- B-002 DeerFlow-native 重构尚未开始（2026-05-22）
- B-004 Phase 2 仍为结构骨架，未接 DeerFlow agent runtime（2026-05-22）
