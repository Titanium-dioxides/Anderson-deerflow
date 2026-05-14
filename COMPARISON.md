# COMPARISON.md — 移植版 vs 原版 Archon + Rethlas 差异全景

> 生成时间: 2026-05-14 20:31 CST
> 对比基准: `/home/zdzdhd/ai4math/Archon` + `/home/zdzdhd/ai4math/Rethlas`

---

## 一、规模对比

| 维度 | 原版 Archon | 原版 Rethlas | 移植版 deerflow |
|------|:-----------:|:------------:|:---------------:|
| 文件数 | 201 | — | 124 |
| 代码行数 (工作流核心) | ~5,450 | ~1,500 | 2,294 |
| 运行时脚本 | 10 | 0 | 0 |
| 工作流引擎 | Claude Code CLI + bash | Codex CLI + bash | LangGraph StateGraph |
| 状态管理 | `.archon/` 文件系统 | 文件系统 + MCP memory | 纯内存 `ArchonState` |

---

## 二、工作流节点对比

### archon_workflow (3 节点 vs 4 节点)

| 节点 | 原版 Archon | 移植版 | 差距 |
|------|:-----------:|:------:|:----:|
| planner | ✅ Plan Agent: 读取 journal、识别 4 种失败模式、生成非形式化指引、子目标分解、并行Agent协调 | ✅ 失败模式识别 (5种)、指引生成、目标提取 (Phase 2)、local+remote搜索 (Phase 2) | ⚠️ 无并行Agent协调、无子目标分解 |
| prover | ✅ LSP 驱动: `lean_goal` → 策略决策 → `lean_multi_attempt` → 三级验证阶梯 | ✅ 增量编译 `_verify_file`、结构化工位提取 `_extract_goal`、自动化策略级联 `_try_tactics_cascade_all` (Phase 3) | ✅ 核心能力已迁移 |
| reviewer | ✅ `lake build` + sorry 计数 | ✅ 失败模式分布统计 | ✅ |
| review_agent | ✅ 分析 `attempts_raw.jsonl` → 写入 `summary.md`、`milestones.jsonl`、`recommendations.md` | ✅ 写入 `archon-journal/session_N/{summary, milestones, recommendations}` | ⚠️ 缺少实际 Lean error/代码变更记录 (需 LSP) |
| **总计** | 3 节点 + 1 代理 | 4 节点 | ✅ 超出原版 |

### unified_prover (7 节点)

| 阶段 | 原版 Rethlas | 移植版 | 差距 |
|------|:-----------:|:------:|:----:|
| search | ✅ Codex MCP 调用 `search_arxiv_theorems` | ✅ `leansearch.net` HTTP API | ⚠️ 远程搜索有无类似 Coverage |
| generator | ✅ 10 个自适应推理 Skills | ✅ standalone prompt (Phase 1 重写)，保留了策略框架 | ❌ 失去子技能模块化、无记忆系统 |
| verifier | ✅ 3 个子 Skills + JSON schema 验证 | ✅ standalone prompt (Phase 1 重写)，保留 strict verdict | ❌ 失去 HTTP 独立部署能力 |
| failure_report | ✅ 报告生成 | ✅ | ✅ |
| planner/prover/reviewer | N/A (Archon 部分) | ✅ | ✅ |
| review_agent | N/A | ✅ | ✅ |

---

## 三、核心能力逐项对照

### ✅ 已实现 (移植度 ≥ 80%)

| 能力 | 原版 | 移植版 |
|------|------|--------|
| **LangGraph StateGraph 编排** | ❌ 无 (bash 循环) | ✅ planner→prover→reviewer→review_agent→loop |
| **plan→prover→reviewer 循环** | ✅ | ✅ |
| **Rethlas generate→verify→repair** | ✅ (≤3 轮) | ✅ (≤3 轮) |
| **非形式化证明→Lean 形式化** | ✅ | ✅ |
| **Lean 编译失败→Rethlas 阅读理解** | ✅ | ✅ (archon_feedback) |
| **增量编译** | ✅ `lake env lean <file>` | ✅ `_verify_file()` (Phase 1) |
| **结构化 Lean 错误解析** | ✅ LSP diagnostic | ✅ `_parse_lean_errors()` + `_classify_error()` (Phase 1) |
| **自动化策略级联** | ✅ rfl→simp→...→grind (9 策略) | ✅ rfl→simp→ring→linarith→omega→aesop→grind (7 策略, Phase 3) |
| **目标提取** | ✅ `lean_goal(file, line)` LSP | ✅ `_extract_goal()` 文件扫描 (Phase 2) |
| **失败模式识别** | ✅ 4 种 (missing infra / wrong construction / no search / early stop) | ✅ 5 种 (+ typeclass, Phase 2) |
| **Attempt 历史跟踪** | ✅ `task_results/<file>.md` | ✅ `attempt_history` 列表 (含 strategy/result/error/mode) |
| **审查期刊** | ✅ summary.md + milestones.jsonl + recommendations.md | ✅ session_N/{summary, milestones, recommendations} + PROJECT_STATUS.md |
| **用户提示注入** | ✅ `USER_HINTS.md` 文件 | ✅ `user_hints` 状态字段 |
| **Lean LSP MCP 配置** | ✅ `extensions_config.json` | ✅ |
| **lean-lsp-mcp server** | ✅ 独立 Python MCP server | ✅ (从原版复制) |
| **42 个 Lean 参考文档** | ✅ `skills/lean4/references/` | ✅ `skills/custom/archon-lean4/references/` |

### ⚠️ 部分实现 (移植度 30-70%)

| 能力 | 原版 | 移植版 | 差距 |
|------|------|--------|------|
| **Mathlib 搜索** | `lean_leansearch` (LSP 语义搜索) + `lean_local_search` (rg) | `_search_mathlib` (leansearch.net) + `_local_lean_search` (grep 降级) | 无 LSP 语义搜索，grep 比 rg 慢 |
| **Planner 指引生成** | 读取 journal + 识别失败模式 + 子目标分解 + 并行协调 | 失败模式识别 + goal context + 搜索注入 | 无子目标分解、无 Agent 协调 |
| **Review Agent 详尽程度** | 逐 attempt 分析 code_tried + lean_error + goal_before/after | 只含 strategy + lean_error | 缺少实际代码变更和 goal state |
| **Rethlas 自适应 Skills** | 10 个 Skills (search/counterexample/proving/etc.) | 单 prompt 保留策略框架 | 失去 Skills 模块化 |
| **`exact?` / `apply?` 策略** | LSP hammer premise | ❌ 未实现 | 依赖 LSP 服务器 |
| **Lean LSP 工具在节点中使用** | 实时 `lean_goal` / `lean_leansearch` / `lean_hammer_premise` | 文件扫描模拟 | LSP 工具已配置但不调用 |

### ❌ 未实现 (移植度 0%)

| 能力 | 原版 | 缺失原因 |
|------|------|----------|
| **并行 Prover** | `--max-parallel N` 多 Agent 并行 | deerflow graph 节点串行执行 |
| **全量集成测试** | 测试用 Lean 项目 + error 用例 | 需要 Lean 环境 |
| **Dashboard UI** | React + TypeScript 面板 | 未移植（不在工作流范围内） |
| **Rethlas HTTP 验证服务** | 独立 uvicorn | 直接 LLM 调用替代 |
| **Rethlas 记忆系统** | MCP memory_init + branch_update + 10 个 channels | 不适合 deerflow 纯内存状态 |
| **自动形式化阶段** | `autoformalize` prompt | planner 为 PROVER 阶段 |
| **Polish 阶段** | `polish` prompt (golf + refactor) | 未实现 |
| **初始化脚本** | `init.sh` 创建 .archon/ + 注册插件 | deerflow 自有部署流程 |

---

## 四、关键差距详细说明

### 1. 文件扫描模拟 vs LSP 实时查询 (TODO #4)

原版 prover 的工作方式：
```
lean_goal("Basic.lean", 42) → "n : ℕ ⊢ n + 0 = n"  [~100ms]
LLM: "induction，然后 simp"
lean_multi_attempt(["induction n; simp", "cases n; simp"]) → 哪个编译通过
lean_diagnostic_messages → 即时反馈
```

移植版 prover：
```
_extract_goal(ws, "Basic.lean", "42") → "theorem add_zero (n : ℕ) : n + 0 = n := by\n  sorry"
                                                                          [文件扫描，含无关内容]
LLM: 盲写全部代码
_write → _verify_file → 一次性检查
```

LSP 的优势：精确、快速、交互式。文件扫描无法获取编译时目标状态。

### 2. Prover 不验证 LLM 修改区域 (TODO #2)

原版通过 LSP 即时诊断确保 LLM 不越界修改。移植版完全信任 LLM。

### 3. 无子目标分解 (TODO 未收录)

原版 plan agent 会识别"这个 sorry 太复杂，分 3 个子目标"并逐步指派。
移植版 planner 只能生成指引，没有策略性的证明策略重排。

### 4. Review Agent 缺少代码变更记录 (TODO #3)

原版 review agent 读取 `attempts_raw.jsonl` 获知每次编辑的 old_text→new_text。
移植版只有 attempt 级别的摘要，无细粒度变更追踪。

---

## 五、TODO 覆盖情况

| # | 描述 | 优先级 | 影响 |
|:-:|------|:------:|:----:|
| 1 | `exact?` / `apply?` 策略 | 🔴 高 | 级联策略不全 |
| 2 | Prover diff 保护 | 🔴 高 | LLM 可能破坏已有证明 |
| 3 | Review Agent 记录代码变更 | 🔴 高 | journal 不够详细 |
| 4 | LSP 工具集成 | 🟡 中 | prover 交互性不足 |
| 5 | 全量集成测试 | 🟡 中 | 无端到端验证 |
| 6 | 并行 Prover | 🟡 中 | 大项目效率低 |
| 7 | 精确时间戳 | 🟢 低 | journal 时间不准 |
| 8 | ripgrep 加速 | 🟢 低 | 搜索速度 |
| 9 | USER_HINTS 持久化 | 🟢 低 | 用户交互接口 |
| 10 | .archon-journal .gitignore | 🟢 低 | 工作区整洁 |

---

## 六、总结

```
核心工作流:  ██████████ 100%  (planner→prover→reviewer→review_agent)
Lean 交互:   ████████░░  80%  (增量编译 ✅, LSP ❌)
错误处理:    ██████████ 100%  (结构化解析 ✅, 失败模式 ✅)
计划智能:    ███████░░░  65%  (模式识别 ✅, 子目标分解 ❌)
证明策略:    ████████░░  78%  (级联 7/9 策略)
搜索能力:    ██████░░░░  60%  (远程+本地 ✅, LSP 语义 ❌)
审查能力:    ██████░░░░  60%  (期刊 ✅, 代码变更 ❌)
并行性:      ██░░░░░░░░  20%  (串行)
端到端测试:  ░░░░░░░░░░   0%  (无)
UI:          ░░░░░░░░░░   0%  (无)

综合移植度: ███████░░░  68%
```
