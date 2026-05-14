# TODO.md — 待解决问题

> 未完成的功能、已知问题、待改进项。按优先级排列。

---

## 高优先级

### 1. `exact?` / `apply?` 策略未实现
- **描述:** 原版 Archon 的 auto-tactics cascade 包含 `exact?` 和 `apply?`（LSP 查询 mathlib），移植版未实现
- **障碍:** 依赖 Lean LSP MCP 服务器，当前 deerflow graph 节点无法直接调用 MCP 工具
- **可能的方案:** 启动 lean-lsp-mcp 子进程，通过 stdin/stdout JSON-RPC 通信
- **关联:** `_AUTO_TACTICS` 列表（Phase 3）

### 2. Prover 不检查原文件 `sorry` 外部分是否被 LLM 修改
- **描述:** 当前 prover 发送整个文件给 LLM 并信任它"不修改 sorry 以外内容"，但 LLM 可能意外破坏已有证明
- **方案:** LLM 返回后做 diff 检查，只接受仅修改了 `sorry` 区域的变更

### 3. Review Agent 缺少 Lean 目标原语
- **描述:** 原版 review agent 读取 `attempts_raw.jsonl`（含 `lean_error`, `goal_state`, `code_change`），移植版只记录 `lean_error` 字符串
- **方案:** review agent 应记录实际尝试的 Lean 代码片段（old_text → new_text）

---

## 中优先级

### 4. Lean LSP 工具未在 prover 中实际使用
- **描述:** `extensions_config.json` 配置了 lean-lsp MCP server，但 graph 节点从未调用
- **影响:** 无法获取精确 goal state、无法使用 `lean_hammer_premise`、`lean_leanfinder` 等
- **参见:** Phase 2 目标提取用文件扫描替代，非 LSP 方式

### 5. 无全量集成测试
- **描述:** 冒烟测试只覆盖纯函数逻辑（L0-L2），未验证完整工作流（L4）
- **障碍:** 需要 Lean 环境 + deerflow LangGraph 运行时才能跑完整测试
- **测试样本:** `tests/fixtures/sample.lean`

### 6. 无并行 prover 支持
- **描述:** 原版 Archon 支持 `--max-parallel N`，多文件并行证明。移植版串行
- **扩展性:** 大项目（>10 文件）单人证明效率低

---

## 低优先级

### 7. prover 的 attempt_history 缺少精确时间戳
- **描述:** 每条 attempt 记录无时间戳，review_agent 写入 journal 时用循环开始时间替代

### 8. `_local_lean_search` 缺少 ripgrep 加速
- **描述:** 当前用 grep 降级，搜索 mathlib 主要子目录。安装 ripgrep 后可自动提速并全量搜索

### 9. 无用户提示（USER_HINTS）持久化
- **描述:** `user_hints` 字段存在状态中，但无文件持久化接口。原版 Archon 通过 `.archon/USER_HINTS.md` 文件交互

### 10. 无 .archon-journal 目录的 .gitignore 建议
- **描述:** `review_agent` 在 `{ws}/.archon-journal/` 写入 journal 文件，应建议用户 `.gitignore` 排除
