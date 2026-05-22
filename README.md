# archon-deerflow

## 当前定位

本仓库进入 **新版本重构阶段**。

目标不是继续在旧实现上增量修补，而是：

- 保留 `source_paper.md` 对应的论文级能力
- 对齐 `Archon/` 与 `Rethlas/` 原始实现的 agent 编排逻辑
- 用 DeerFlow 的原生编排、文件管理、sandbox、tools、subagents、checkpointer、runtime history 重新实现整条流程

---

## 开发入口

当前开发以以下文档为准：

1. `DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md`
   - 最高级迁移规范
2. `DEVELOPMENT_ROADMAP.md`
   - 分阶段开发路线
3. `TODO.md`
   - 当前待办与阶段推进
4. `BLOCKERS.md`
   - 当前阻塞项
5. `KNOWLEDGE.md`
   - 已确认知识
6. `AUDIT.md`
   - 当前实现审计
7. `SMOKE_TEST.md`
   - 修改后的最小验证规则
8. `MIGRATION_LOG.md`
   - 迁移变更记录

---

## 三套基线

新版本开发同时对齐三套基线：

- **论文基线**：`source_paper.md`
- **原实现基线**：`Archon/`、`Rethlas/`
- **DeerFlow 基线**：`deer-flow/` 与 `DEERFLOW_REFERENCE.md`

---

## 当前状态

- 旧版分析/审计/比较文档已进入清理阶段
- 新版迁移规范与路线图已建立
- 下一步按 `DEVELOPMENT_ROADMAP.md` 进入 `Phase 1 — DeerFlow Runtime 骨架`

---

## 目录说明

- `Archon/`
  - 原始 Archon 参考实现
- `Rethlas/`
  - 原始 Rethlas 参考实现
- `deer-flow/`
  - DeerFlow 参考实现与文档
- `source_paper.md`
  - 原论文文本
- `DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md`
  - 迁移最高规范
- `DEVELOPMENT_ROADMAP.md`
  - 分阶段执行路线

---

## 开发原则

一句话：

> **保留算法结构，替换运行时基础设施。**

即：

- 论文与原实现决定 proof-domain workflow
- DeerFlow 决定 runtime / workspace / tools / sandbox / subagents / history

