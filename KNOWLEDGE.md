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

