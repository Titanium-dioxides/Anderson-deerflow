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

### B-001 外部原始代码对齐尚未完成

- **状态**: active
- **范围**: Rethlas / Archon 编排完全对齐
- **说明**: 当前仓库已纳入 `Archon/`、`Rethlas/` 参考副本，但尚未逐项建立“论文 -> 原实现 -> DeerFlow 新实现”的行为映射表。
- **影响**: 在进入大规模代码重构前，需先完成对齐清单，否则易出现能力回退。

### B-002 DeerFlow-native 重构尚未开始

- **状态**: resolved
- **范围**: workflow runtime
- **说明**: Phase 1 已启动，最小 runtime skeleton 已落地到 `overlay/backend/workflows/phase1_runtime.py`。
- **解除时间**: 2026-05-22

### B-003 DeerFlow Gateway 路径尚未接通新 workflow

- **状态**: active
- **范围**: Phase 1 runtime integration
- **说明**: 当前已建立 Phase 1 graph skeleton，但尚未接通 DeerFlow Gateway 实际运行入口。
- **影响**: 目前能完成代码与目录骨架验证，但还不能视为“通过 DeerFlow runtime 完整启动”。

### B-004 Phase 2 仍为结构骨架，未接 DeerFlow agent runtime

- **状态**: resolved
- **范围**: Rethlas generation / verification
- **说明**: Phase 2 的 generation / verification 已切到 DeerFlow agent runtime，并建立了最小 skill tool 暴露层。
- **解除时间**: 2026-05-22

### B-005 Phase 2 缺少 recursive proving 的 DeerFlow subagent runtime

- **状态**: active
- **范围**: Rethlas recursive exploration
- **说明**: 当前 Phase 2 已接入 generation / verification runtime，但 recursive proving 仍未建立 DeerFlow subagent 执行路径。
- **影响**: 论文中的多路径递归探索能力尚未恢复。

---

## 已解除 Blockers

- B-002 DeerFlow-native 重构尚未开始（2026-05-22）
- B-004 Phase 2 仍为结构骨架，未接 DeerFlow agent runtime（2026-05-22）
