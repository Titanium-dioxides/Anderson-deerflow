# TODO.md — 待解决问题

> 未完成的功能、已知问题、待改进项。按优先级排列。
> 上次更新: 2026-05-14

---

## 🔴 高优先级 — 影响正确性/安全性

### ~~B1. LSP 工具集成~~ ✅ 2026-05-14 已解决
### ~~B2. exact?/apply? 策略~~ ✅ 2026-05-14 B1 解决后自动解除

### R1. 文件 I/O 绕过 Sandbox
- **描述:** 直接使用 `Path.write_text()` / `Path.read_text()` 操作宿主机文件系统，不走 DeerFlow 的 sandbox 隔离层
- **影响:** 在 Docker 容器部署中可能路径错乱；无权限隔离
- **修复方案:** 改为 `sandbox.write_file()` / `sandbox.read_file()`。当前 graph 节点无 sandbox 实例，需集成到节点入口
- **依赖:** 需要 graph 节点能获取到 sandbox 实例（需 middleware 改造）
- **估计:** 1h

### R2. Bash 执行绕过 Sandbox
- **描述:** 直接调用 `subprocess.run()` + 手动拼接 PATH 来执行 `lake build`、`lake env lean`、`grep` 等
- **影响:** 无沙箱隔离，无超时保护（当前 300s），可能影响宿主机
- **修复方案:** 改为 `sandbox.execute_command()`。Sandbox 自动处理 PATH 和超时
- **估计:** 0.5h

### R3. Lean 编译路径未标准化
- **描述:** `_bash("lake env lean {f}")` 直接调 Lean，未通过 `lean_verify` LSP 工具或 sandbox
- **B1 注:** 已通过 `_call_with_lsp()` 为 LLM 提供了 LSP 工具通路，但 `_verify_file()` 仍手动 bash
- **修复方案:** `lean_multi_attempt` LSP 工具 → `lean_diagnostic_messages` 获取结果
- **估计:** 1h

### R4. Skills 未注册到 DeerFlow Skills 系统
- **描述:** `overlay/skills/custom/archon-lean4/SKILL.md` 是原版 Archon 的技能文件，但未被 DeerFlow 的 `apply_prompt_template()` 加载
- **影响:** 技能知识不会自动注入 agent 的 system prompt
- **修复方案:** 将 SKILL.md 软链接或复制到 `deer-flow/skills/` 目录下，DeerFlow 自动加载
- **估计:** 0.2h

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

### Y3. 模型名称硬编码
- **描述:** `_model()` 硬编码 `"deepseek-v4"`，不从 `config.yaml` 读取
- **方案:** `app_config.models[0].name` 或环境变量
- **估计:** 0.2h

### Y4. 无 ThreadState 集成
- **描述:** `ArchonState(dict)` 自定义状态，未使用 `ThreadState(AgentState)`
- **影响:** 无 checkpoint、无消息持久化
- **估计:** 2h

### Y5. 文件扫描用 grep 而非 LSP
- **描述:** `_scan()` 用 `grep -rn sorry` 扫描 .lean 文件，未使用 `lean_file_outline` LSP 工具
- **影响:** 无法区分声明级 sorry 和注释中的 sorry 文本
- **方案:** LSP tool `lean_file_outline` + `lean_diagnostic_messages`
- **估计:** 1h

### Y6. 错误处理用 try/except + print
- **描述:** 无 middleware 统一错误处理，`_bash()` 内部 timeout=300 硬编码
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

### G4. 图注册 via overlay 而非原生
- **描述:** `overlay/backend/langgraph.json` 手动复制到 deer-flow 实例
- **方案:** 改为 deer-flow 原生 `backend/langgraph.json` + `make config`
- **估计:** 0.2h

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
