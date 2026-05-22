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
