# BLOCKERS.md

## 说明

本文件只记录两类内容：

1. **真正的 blocker** — 外部依赖缺失 / 环境限制 / 架构约束
2. **已解除的 blocker 历史**

未实现但不构成阻塞的项放入 `TODO.md`。

---

## 当前 Blockers

### B-008 Phase 3 autoformalize JSON 解析不稳定

- **状态**: resolved
- **范围**: Phase 3 Archon Scaffolding
- **说明**: `_extract_json_object` 已增加括号深度计数 + 多层 markdown 剥离；`autoformalize_node` 已增加最多 2 次 retry（解析失败时将错误信息反馈给 LLM 要求重新输出）。
- **解除时间**: 2026-05-25

### B-009 定理检索并行 HTTP fallback 未收敛到 DeerFlow MCP 主路径

- **状态**: resolved
- **范围**: 搜索渠道架构
- **说明**: `_invoke_named_tool` 现在将所有搜索调用（lean_theorem_search、search_and_verify、web_search）路由通过 `get_available_tools()` → `config.yaml` 工具注册表。直接 HTTP 调用（Matlas/LeanSearch/Loogle）是注册工具的**内部实现细节**，不再绕过工具注册表。`_web_search`/`_web_fetch` 的直连 HTTP fallback 受 `RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK` 环境变量保护，默认关闭。
- **解除时间**: 2026-05-25

---

## 待解决的审计差距（来自 AUDIT.md）

| 差距 | 优先级 |
|------|:------:|
| Phase 3 autoformalize JSON 鲁棒性 | 🟡 |
| Phase 2 skills → memory channel 写入不够稳定 | 🟡 |
| theorem retrieval HTTP fallback → MCP 收敛 | 🟡 |
| `lake build` 首次 Mathlib 下载可能超时 | 🟢 |
| Lean LSP `lean_hammer_premise` / `lean_state_search` 未实现 | 🟢 |
| Phase 2 repair loop 闭环验证（端到端多次 repair 的实际调用链） | 🔴 |

---

## 已解除 Blockers

| 编号 | 说明 | 解除时间 |
|:----:|------|:--------:|
| B-001 | 论文→原实现→新实现 对齐表（AUDIT.md 45 项） | 2026-05-24 |
| B-002 | DeerFlow-native 重构启动 | 2026-05-22 |
| B-003 | Gateway + Docker + SDK 全路径验证 | 2026-05-24 |
| B-004 | Phase 2 generation/verification 接入 DeerFlow agent runtime | 2026-05-22 |
| B-005 | recursive proving → subagent `task` tool | 2026-05-24 |
| B-006 | runtime history / checkpointer 持久化 | 2026-05-24 |
| B-007 | Phase 2 memory channel writes (`_record_skill_outputs` + auto-discovery fallback) | 2026-05-25 |
| B-008 | Phase 3 autoformalize JSON retry + brace-counting parser | 2026-05-25 |
