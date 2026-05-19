# TODO.md — 待解决问题

> 未完成的功能、已知问题、待改进项。按优先级排列。
> 上次更新: 2026-05-19

---

## 🔴 高优先级 — 影响正确性/安全性

### ~~B1. LSP 工具集成~~ ✅ 2026-05-14 已解决
### ~~B2. exact?/apply? 策略~~ ✅ 2026-05-14 B1 解决后自动解除

### ~~A1. ArchonState/UnifiedState 未继承 ThreadState~~ ✅ 2026-05-19
- **描述:** 改为 `TypedDict` + `Annotated` reducers（与 ThreadState 风格兼容）。未直接继承 ThreadState 因为外层的 graph 是编排层，不需要 sandbox 字段。
- **变更:** `class ArchonState(TypedDict)` / `class UnifiedState(TypedDict)`，messages 使用 `Annotated[list, add_messages]`
- **遗留:** 如需通过 `MemorySaver()` 持久化外层 Graph，需要确保所有字段序列化兼容

### ~~A2. `_bash()`/`_read()`/`_write()` 绕过 SandboxMiddleware~~ ✅ 2026-05-19
- **变更:** 引入 `_sandbox_context()` 上下文管理器，所有 I/O 操作在此上下文内执行。acquire/release 配对，避免泄漏
- **变更:** 硬编码 `"archon-workflow"` → 从 state['thread_id'] 读取
- **变更:** `except: pass` → `logger.warning(...)`

### ~~A3. `create_deerflow_agent()` 在 for 循环内反复构建+销毁~~ ✅ 2026-05-19
- **变更:** agent 在 prover 节点入口处一次性构建（`_build_prove_agent()`），所有 pending 文件在循环内复用同一个 agent
- **变更:** `get_available_tools()` 在 agent 构建前调用一次（C1）
- **变更:** 每文件调用 `agent.invoke()` 使用不同的 thread_id，checkpoint 按文件隔离

### ~~A4. `_verify_file()` 仍手动 bash~~ ✅ 2026-05-19 (A2 自动解)
- **说明:** 改为通过 sandbox 上下文管理器执行 `lake env lean`

### ~~B1. 手动 skills 加载~~ ✅ 2026-05-19
- **变更:** 优先调用 `apply_prompt_template()`，失败时才回退到手动 `_load_skills_prompt()`

### ~~B2. 跨文件重复代码 ~800 行~~ ✅ 2026-05-19
- **变更:** 抽取共享模块 `workflows/shared.py`，包含：`classify_error`, `parse_lean_errors`, `format_errors`, `extract_goal`, `classify_failure`, `make_attempt`, `extract_code`, `extract_json`, `goal_context`, `AUTO_TACTICS`, `FAILURE_KEYWORDS`

### ~~B5. `_safe_invoke()` 手动 tool-calling loop~~ ✅ 2026-05-19
- **变更:** prover 节点不再使用 `_safe_invoke()`，改用 `create_deerflow_agent()` 的内建 tool-calling loop + `LoopDetectionMiddleware`
- **关联文件:** `archon_graph.py`, `unified_graph.py` 中精简了 `_safe_invoke()` 相关代码

### ~~C1. `get_available_tools()` 在 for 循环内重复调用~~ ✅ 2026-05-19
### ~~C2. HumanMessage 内容过于笼统~~ ✅ 2026-05-19
### ~~C3. `_PATHS` 定义但未使用~~ ✅ 2026-05-19
### ~~C4. `_bash()` sandbox fallback 静默失败~~ ✅ 2026-05-19
### ~~C5. 硬编码 sandbox acquire ID~~ ✅ 2026-05-19

---

## 🟡 中优先级 — 设计模式偏离

### B1. 手动 skills 加载替代 apply_prompt_template()
- **来源:** 2026-05-19 实现规范审计
- **描述:** `_load_skills_deerflow()` 手动遍历 skills storage → 拼接 SystemMessage，未用 `apply_prompt_template()`
- **差距:** 缺少 skills 白名单过滤、memory 上下文注入、sandbox 信息注入、工具列表注入
- **方案:** `apply_prompt_template(available_skills=set(["archon-lean4"]))`
- **估计:** 0.5h

### B2. 跨文件重复代码 ~800 行
- **来源:** 2026-05-19 实现规范审计
- **描述:** `archon_graph.py` 和 `unified_graph.py` 共享 `_classify_error`、`_parse_lean_errors`、`_verify_file`、`_try_tactics_cascade`、`_try_tactics_cascade_all`、`_AUTO_TACTICS`、`_extract_goal`、`_local_lean_search`、`_bash`、`_read`、`_write`、`_model`、`_get_model_name`、`_safe_invoke`、`_get_all_tools`、`_load_skills_deerflow` 等函数
- **方案:** 抽取到共享模块 `workflows/lean_utils.py`
- **估计:** 1h

### B3. `_scan()` 仍用 grep 而非 LSP
- **来源:** 2026-05-19 实现规范审计
- **描述:** 扫描 sorry 使用 `grep -rn 'sorry' --include='*.lean'`，而非 `lean_file_outline` LSP 工具
- **方案:** LSP 工具 `lean_file_outline` 可获取文件大纲（含所有声明位置与状态）
- **估计:** 0.5h

### B4. `_local_lean_search()` 手动 grep 而非 LSP
- **来源:** 2026-05-19 实现规范审计
- **描述:** 本地搜索用 grep 模拟，无语义搜索能力，且无 ripgrep 加速
- **方案:** LSP `lean_local_search` 工具已通过 MCP cache 加载，注册为工具后 LLM 可自选调用
- **估计:** 0.5h

### B5. `_safe_invoke()` 手动 tool-calling loop
- **来源:** 2026-05-19 实现规范审计
- **描述:** 手动实现有限轮次（max_turns=3）的 tool-calling 循环
- **方案:** `create_agent()` 自动提供 tool-calling loop + `LoopDetectionMiddleware` 死循环检测
- **估计:** 0.5h

### ~~R3. Lean 编译路径未标准化~~
- **描述（旧）:** `_bash("lake env lean {f}")` 直接调 Lean
- **状态:** → 合并到 A4（更精确的审计编号）
- **估计:** (已重分类)

### ~~R1. 文件 I/O 绕过 Sandbox~~ ✅ 2026-05-14（已标记，但规范审计指出修复不彻底 → 见 A2）
### ~~R2. Bash 执行绕过 Sandbox~~ ✅ 2026-05-14（已标记，但规范审计指出修复不彻底 → 见 A2）

---

## 🟢 低优先级 — 可优化

### C1. `get_available_tools()` 在 for 循环内重复调用
- **来源:** 2026-05-19 实现规范审计
- **描述:** prover 的 `for t in pending` 循环中每次迭代都调用 `get_available_tools()`（含 MCP cache 访问）
- **方案:** 移出循环，在进入 prover 节点时调用一次
- **估计:** 0.1h

### C2. HumanMessage 内容过于笼统
- **来源:** 2026-05-19 实现规范审计
- **描述:** 传递给子 agent 的提示词仅描述步骤格式，未嵌入具体目标信息（goal_sig、hint 等）
- **方案:** 将 `goal_sig`、`hint`、失败模式等信息嵌入 HumanMessage，agent 无需先读文件就知目标
- **估计:** 0.2h

### C3. `_PATHS` 定义但未使用
- **来源:** 2026-05-19 实现规范审计
- **描述:** `unified_graph.py` 定义了 `_PATHS: dict[str, Path] = {}` 但从未被代码实际调用
- **方案:** 移除或改用
- **估计:** 0.1h

### C4. `_bash()` sandbox fallback 静默失败
- **来源:** 2026-05-19 实现规范审计
- **描述:** `except Exception: pass` 丢失异常信息
- **方案:** 改为 `except Exception as e: logger.warning(...)` 或 `logger.exception(...)`
- **估计:** 0.1h

### C5. 硬编码 sandbox acquire ID
- **来源:** 2026-05-19 实现规范审计
- **描述:** `"archon-workflow"` 作为 sandbox acquire ID 写死
- **方案:** 从 ThreadDataState 获取 thread_id
- **估计:** 0.1h

## 🟢 原有待办（低优先级）

### G1. 串行 for 循环 → Sub-agents
- **描述:** prover 内 `for t in pending` 串行处理，未被 `deerflow.subagents` 并行化
- **影响:** 大项目效率低
- **方案:** `spawn_subagent()` 替代串行
- **注:** 实现 A3 修复后此问题可同步解决（一次性 agent + 多文件描述）
- **估计:** 2h

### G2. 手动提示词拼接 → apply_prompt_template()
- **注:** 已与 B1 合并

### G3. 路径常量硬编码
- **描述:** `_RETHLAS_DIR = Path(__file__).parent...` 等路径不从配置读取
- **估计:** 0.2h

### ~~G4. 图注册~~ ✅ 已原生注册
- `deer-flow/backend/langgraph.json` 已含 `archon_workflow` 和 `unified_prover`

### 7. prover 的 attempt_history 缺少精确时间戳
### 8. `_local_lean_search` 缺少 ripgrep 加速（已有 LSP lean_local_search 替代）
### 9. 无用户提示（USER_HINTS）持久化
### 10. 无 .archon-journal 目录的 .gitignore 建议

---

## 新增待办（Subagent 审计，2026-05-19）

### D1. 使用 SubagentExecutor 替代 create_deerflow_agent
- **来源:** SUBAGENT_AUDIT.md
- **描述:** 当前 prover 节点内 `create_deerflow_agent().invoke()` 串行处理文件。规范做法是用 `SubagentExecutor` + `task` 工具，每个文件 spawn 一个 subagent
- **影响:** 失去并行、异步、cancellation、sandbox 继承
- **估计:** 2h

### D2. 启用 RuntimeFeatures(subagent=True)
- **描述:** 注入 SubagentLimitMiddleware + task 工具
- **估计:** 0.1h

### D3. sandbox 跨 agent 共享
- **描述:** subagent 通过 sandbox_state 继承父 agent 的 sandbox，不独立 acquire/release
- **估计:** 0.5h

## 新增待办（SVG 架构差距，2026-05-19）

| 编号 | 差距 | 来源 | 优先级 |
|:----:|:-----|:----:|:------:|
| S1 | Rethlas 10 自适应 Skills 拆分为独立模块 | rethlas_agent.svg | 🟡 |
| S3 | 回环策略 ①Ask Informal(细化) 独立实现 | whole_pipeline.svg | 🟢 |
| S5 | planner 节点做 LLM 驱动的主动分解 | Agent_system_with_tools.svg | 🟢 |
| S9 | _search_mathlib 增强到 arXiv 级别 | rethlas_agent.svg | 🟢 |

## Principle 合规差距（2026-05-19）

| 编号 | 差距 | 违反原则 | 优先级 |
|:----:|:-----|:--------:|:------:|
| PR1 | unified_graph planner_node 未调 LLM（与 archon_graph 不一致）| P2/P3 | 🔴 |
| PR2 | autoformalize 独立阶段缺失 | P3 | 🔴 |
| PR3 | polish 独立阶段缺失 | P3 | 🔴 |
| PR4 | Rethlas 10 自适应 Skills 未移植 | P3/P4 | 🟡 |
| PR5 | 回环策略三级递进未独立实现 | P3 | 🟡 |
| PR6 | Rethlas 多路并行探索（单路径线性）| P4 | 🟡 |
| PR7 | Principle.md 引用 IMPLEMENTATION_AUDIT.md 已删除 | — | 🟢 改引用 AUDIT_V2.md |

## 修复记录

| 日期 | 修复项 | 说明 |
|------|--------|------|
| 2026-05-14 | B1 | LSP 工具集成到 prover（`_call_with_lsp`） |
| 2026-05-14 | B2 | exact?/apply? 通过 `lean_hammer_premise` 可用 |
| 2026-05-14 | R1 | 文件 I/O 改为 sandbox 优先（审计指出不彻底 → A2）|
| 2026-05-14 | R2 | Bash 改为 sandbox 优先（审计指出不彻底 → A2）|
| 2026-05-14 | R4 | Skills 内容注入 SystemMessage（审计指出不彻底 → B1）|
| 2026-05-14 | Y3 | 模型名从 config 读取 |
| 2026-05-14 | G4 | 确认已原生注册到 deer-flow langgraph.json |
| 2026-05-14 | Y2 | _get_lsp_tools() → _get_all_tools() |
| 2026-05-14 | Y6 | _safe_invoke() 安全调用含重试（审计指出不彻底 → B5）|
| 2026-05-14 | G1 | ThreadPoolExecutor 并行证明 |
| 2026-05-14 | G3 | _resolve_path() 可配置路径 |
| 2026-05-19 | — | 新增实现规范审计，归档为 IMPLEMENTATION_AUDIT.md |
| 2026-05-19 | — | 修复 A1-A5,B1,B2,B5,C1-C5（大版本重构）|
| 2026-05-19 | — | 新增 Subagent 审计，归档为 SUBAGENT_AUDIT.md |
| 2026-05-19 | — | D1-D3 修复: SubagentExecutor 替代 create_deerflow_agent |
