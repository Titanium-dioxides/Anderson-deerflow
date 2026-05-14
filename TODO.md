# TODO.md — 待解决问题

> 未完成的功能、已知问题、待改进项。按优先级排列。
> 上次更新: 2026-05-14

---

## 🔴 高优先级 — 影响正确性/安全性

### ~~B1. LSP 工具集成~~ ✅ 2026-05-14 已解决
### ~~B2. exact?/apply? 策略~~ ✅ 2026-05-14 B1 解决后自动解除

### ~~R1. 文件 I/O 绕过 Sandbox~~ ✅ 2026-05-14
- `_read()` / `_write()` 改为先尝试 `sandbox.read_file()` / `sandbox.write_file()`，失败回退到直接 Path I/O

### ~~R2. Bash 执行绕过 Sandbox~~ ✅ 2026-05-14
- `_bash()` 改为先尝试 `sandbox.execute_command()`，失败回退到直接 subprocess

### R3. Lean 编译路径未标准化
- **描述:** `_bash("lake env lean {f}")` 直接调 Lean，未通过 `lean_verify` LSP 工具或 sandbox
- **B1 注:** 已通过 `_call_with_lsp()` 为 LLM 提供了 LSP 工具通路，但 `_verify_file()` 仍手动 bash
- **修复方案:** `lean_multi_attempt` LSP 工具 → `lean_diagnostic_messages` 获取结果
- **估计:** 1h

### ~~R4. Skills 未注入 SystemMessage~~ ✅ 2026-05-14
- `_load_skill_content()` + `_DEFAULT_SKILL` 注入 prover 的 SystemMessage

---

## 🟡 中优先级 — 设计模式偏离

### Y1. 手动 StateGraph 而非 create_agent()
- **描述:** 使用手动构建的 `StateGraph(ArchonState)` + 4 个自定义节点，而非 DeerFlow 标准的 `create_agent()` + middleware chain
- **影响:** 无法利用 middleware（sandbox、memory、checkpoint 等）
- **权衡:** 通用 agent 模式不适合数学定理证明的结构化工作流（plan→prove→review 循环）。手动 StateGraph 是合理的 tradeoff，但需要自行补齐 sandbox/middleware
- **估计:** 4h（如需迁移）

### Y2. 手动工具获取
- **描述:** `_get_lsp_tools()` 直接调 `get_cached_mcp_tools()`，未通过 `get_available_tools()` 统一入口
- **影响:** 缺少 tool policy 过滤、配置驱动加载等能力
- **方案:** `get_available_tools()` 替代 `_get_lsp_tools()`
- **估计:** 0.5h

### ~~Y3. 模型名称硬编码~~ ✅ 2026-05-14
- `_model()` 默认 `None` → `_get_model_name()` 从 `get_app_config()` 读取

### ~~Y2. 手动工具获取~~ ✅ 2026-05-14
- `_get_lsp_tools()` → `_get_all_tools()` 使用 `get_available_tools()`
- `_call_with_lsp()` → `_safe_invoke()` 含重试机制

### ~~Y6. 错误处理~~ ✅ 2026-05-14（部分）
- `_safe_invoke()` 含 retries 参数
- `ThreadPoolExecutor` 含 timeout 保护

### Y4. 无 ThreadState 集成
- **描述:** `ArchonState(dict)` 自定义状态，未使用 `ThreadState(AgentState)`
- **影响:** 无 checkpoint、无消息持久化
- **估计:** 2h

### ~~Y6. 错误处理~~ ✅ 2026-05-14
- `_safe_invoke()` 含 retries 参数

### Y4. 无 ThreadState 集成
- **描述:** `ArchonState(dict)` 自定义状态，未使用 `ThreadState(AgentState)`
- **影响:** 无 checkpoint、无消息持久化
- **估计:** 2h

### Y1. 手动 StateGraph 而非 create_agent()
- **描述:** 使用手动构建的 `StateGraph(ArchonState)` + 4 个自定义节点，而非 DeerFlow 标准的 `create_agent()` + middleware chain
- **影响:** 无法利用 middleware（sandbox、memory、checkpoint 等）
- **权衡:** 通用 agent 模式不适合数学定理证明的结构化工作流（plan→prove→review 循环）。手动 StateGraph 是合理的 tradeoff，但需要自行补齐 sandbox/middleware
- **估计:** 4h（如需迁移）
- **估计:** 1h

---

## 🟢 低优先级 — 可优化

### G1. 串行 for 循环 → Sub-agents
- **描述:** prover 内 `for t in pending` 串行处理，未被 `deerflow.subagents` 并行化
- **影响:** 大项目效率低
- **方案:** `spawn_subagent()` 替代串行
- **估计:** 2h

### G2. 手动提示词拼接 → apply_prompt_template()
- **描述:** `SystemMessage(content=...)` 手动拼接，未被 `apply_prompt_template()` 自动注入 skills/memory
- **估计:** 0.5h

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

## 修复记录

| 日期 | 修复项 | 说明 |
|------|--------|------|
| 2026-05-14 | B1 | LSP 工具集成到 prover（`_call_with_lsp`） |
| 2026-05-14 | B2 | exact?/apply? 通过 `lean_hammer_premise` 可用 |
| 2026-05-14 | R1 | 文件 I/O 改为 sandbox 优先 |
| 2026-05-14 | R2 | Bash 改为 sandbox 优先 |
| 2026-05-14 | R4 | Skills 内容注入 SystemMessage |
| 2026-05-14 | Y3 | 模型名从 config 读取 |
| 2026-05-14 | G4 | 确认已原生注册到 deer-flow langgraph.json |
| 2026-05-14 | Y2 | _get_lsp_tools() → _get_all_tools() |
| 2026-05-14 | Y6 | _safe_invoke() 安全调用含重试 |
| 2026-05-14 | G1 | ThreadPoolExecutor 并行证明 |
| 2026-05-14 | G3 | _resolve_path() 可配置路径 |
