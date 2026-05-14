# DeerFlow 基础设施全景分析

> 逐个评估 DeerFlow 的每个模块，判断是否与我们的项目相关、是否有接入价值

---

## 基础设施总览

```
deerflow/
├── config/        ★ 全局配置（模型、工具、沙箱...） ← 已用
├── models/        ★ 模型工厂 create_chat_model()    ← 已用
├── tools/         ★ 工具聚合 get_available_tools()  ← 已用（Y2）
├── mcp/           ★ MCP 工具加载 get_cached_mcp_tools() ← 已用
├── sandbox/       ★ 沙箱执行环境                     ← 已用（R1/R2）
├── skills/        ★ 技能系统 skills/storage/        ← 已用（G2）
├── runtime/       ▷ 运行时（checkpointer, events）   ← 未用
├── subagents/     ▷ 子代理系统                       ← 未用
├── persistence/   ▷ 数据库持久化                     ← 未用
├── agents/        ▷ lead_agent, 中间件链             ← 未用（Y1 pending）
├── guardrails/    ▷ 安全护栏                         ← 未用
├── uploads/       ▷ 文件上传                         ← 未用
├── tracing/       ▷ 链路追踪                         ← 未用
├── reflection/    ▷ 反射工具 resolve_class()         ← 隐含使用
└── utils/         ▷ 工具函数                          ← 未用
```

---

## 逐模块分析表

### 1. config/ — 配置加载

| 属性 | 值 |
|------|-----|
| **API** | `get_app_config()` → `AppConfig` |
| **功能** | 读取 `config.yaml`，提供模型、工具、sandbox、skills 等配置 |
| **已用** | ✅ `_get_model_name()` 读取 `models[0].name` |
| **未用潜力** | `config.tools` → 工具分组；`config.sandbox` → sandbox 配置 |
| **接入难度** | 🟢 低 — 已部分接入 |
| **推荐** | 无需扩展 |

### 2. models/ — 模型工厂

| 属性 | 值 |
|------|-----|
| **API** | `create_chat_model(name, thinking_enabled)` → `BaseChatModel` |
| **功能** | 从 config.yaml 读取模型配置，通过 LangChain 反射创建模型实例。支持 thinking 模式切换 |
| **已用** | ✅ `_model()` 和 `_safe_invoke()` 都使用 |
| **未用潜力** | `.bind_tools()` 方法（✅ 已用）|
| **接入难度** | 🟢 低 — 完全接入 |
| **推荐** | 无需扩展 |

### 3. tools/ — 工具聚合

| 属性 | 值 |
|------|-----|
| **API** | `get_available_tools(groups, include_mcp, model_name, subagent_enabled)` → `list[BaseTool]` |
| **功能** | 聚合三类工具：builtin（present_file, ask_clarification）、configured（sandbox bash/file/web_search）、MCP（via get_cached_mcp_tools）。支持 groups 过滤 |
| **已用** | ✅ Y2 修复后使用 |
| **未用潜力** | `groups` 参数可以只暴露 MCP 工具，不暴露 bash/file 等给 LLM |
| **接入难度** | 🟢 低 — 已接入 |
| **推荐** | 无需扩展 |

### 4. mcp/ — MCP 工具

| 属性 | 值 |
|------|-----|
| **API** | `get_cached_mcp_tools()` → `list[BaseTool]` |
| **功能** | 从 `extensions_config.json` 读取 MCP 服务器配置，建立连接，返回 LangChain 工具。支持 stdio/SSE/HTTP。自动缓存和 mtime 热重载 |
| **已用** | ✅ B1/B2 修复后使用 |
| **未用潜力** | OAuth 支持、工具拦截器 |
| **接入难度** | 🟢 低 — 已接入 |
| **推荐** | 无需扩展 |

### 5. sandbox/ — 沙箱执行环境

| 属性 | 值 |
|------|-----|
| **API** | `get_sandbox_provider() → provider → Sandbox.execute_command()/read_file()/write_file()` |
| **功能** | 抽象沙箱接口。LocalSandboxProvider 本地执行，AioSandboxProvider Docker 隔离。支持虚拟路径映射（`/mnt/user-data/workspace` → 本地目录）|
| **已用** | ✅ R1/R2 修复后使用（`_bash()` / `_read()` / `_write()` 优先调 sandbox） |
| **未用潜力** | `sandbox.grep()` 替代 `_bash("grep ...")`；`sandbox.glob()` 替代 `_bash("find ...")` |
| **接入难度** | 🟢 低 — 已接入，可继续加深 |
| **推荐** | 将 grep 和 find 操作迁移到 `sandbox.grep()` / `sandbox.glob()` |

### 6. skills/ — 技能系统

| 属性 | 值 |
|------|-----|
| **API** | `get_or_new_skill_storage() → storage.load_skills()` → `list[Skill]` |
| **功能** | 从 `skills/` 目录加载 SKILL.md → 解析 YAML front matter + 内容 → 注入 agent system prompt。支持 `allowed-tools` 白名单 |
| **已用** | ✅ G2 修复后使用 |
| **未用潜力** | `allowed-tools` 过滤、技能搜索结果（tool_search）|
| **接入难度** | 🟢 低 — 已接入 |
| **推荐** | 无需扩展 |

### 7. runtime/checkpointer/ — 检查点

| 属性 | 值 |
|------|-----|
| **API** | `get_checkpointer()` → `Checkpointer` (或 `MemorySaver`) |
| **功能** | LangGraph 检查点系统。支持内存 (`MemorySaver`) 和持久化 (`SqliteSaver`, `PostgresSaver`)。配置在 `config.yaml` 的 `checkpointer` 段 |
| **已用** | ❌ 未用 |
| **接入方式** | `w.compile(checkpointer=MemorySaver())` — 一行代码 |
| **收益** | 每次节点执行后自动保存 `ArchonState`；故障后可恢复；LangGraph Studio 可回溯 |
| **接入难度** | 🟢 低 — 一行 `compile(checkpointer=...)` |
| **推荐** | ✅ **建议接入** — 零成本高收益 |

### 8. runtime/events/ — 运行时事件

| 属性 | 值 |
|------|-----|
| **API** | `RunEventStore` → `JsonlRunEventStore(base_dir)` |
| **功能** | 运行事件存储。支持 JSONL 文件、数据库两种后端。记录每次 LLM 调用的 metrics（tokens、cost、duration）|
| **已用** | ❌ 未用 |
| **接入方式** | 创建 `JsonlRunEventStore` 实例，在 `_safe_invoke()` 成功/失败时写入事件 |
| **收益** | 结构化的运行记录，便于分析和调试 |
| **接入难度** | 🟡 中 — 需要在 _safe_invoke 中增加事件写入 |
| **推荐** | ⏳ **暂时不需要** — review_agent 的 journal 已经够用 |

### 9. subagents/ — 子代理系统

| 属性 | 值 |
|------|-----|
| **API** | `SubagentExecutor(config, tools).execute(task)` |
| **功能** | 创建子代理执行独立任务。子代理获得完整中间件链（sandbox、memory...）。支持 per-subagent 的 tools/skills/model 独立配置 |
| **已用** | ❌ 未用。当前用 `ThreadPoolExecutor` 做文件级并行 |
| **接入方式** | 在 `prover` 节点中为每个文件 spawn 一个子 agent |
| **收益** | 子 agent 获得完整中间件链（sandbox 自动获取、错误处理...）|
| **接入难度** | 🔴 高 — `SubagentExecutor` 需要 `SubagentConfig` + 状态管理；收益有限 |
| **推荐** | ❌ **不推荐** — `ThreadPoolExecutor` 更轻量，已经满足需求 |

### 10. persistence/ — 数据库持久化

| 属性 | 值 |
|------|-----|
| **API** | SQLAlchemy 引擎，模型定义（ThreadMeta, RunEvent, Feedback...）|
| **功能** | 数据库 ORM。存储对话元数据、运行记录、用户反馈 |
| **已用** | ❌ 未用 |
| **推荐** | ❌ **不推荐** — 证明工作流不需要数据库 |

### 11. agents/ (中间件链) — 中间件

| 属性 | 值 |
|------|-----|
| **内容** | 7 个中间件：SandboxMiddleware, TokenUsageMiddleware, MemoryMiddleware, SummarizationMiddleware, ToolErrorHandlingMiddleware, LoopDetectionMiddleware, ClarificationMiddleware |
| **已用** | ❌ 未用。当前在 Layer 3 独立实现 |
| **关键 gap** | TokenUsageMiddleware 记录 LLM 调用成本 |
| **推荐** | ⏳ **选择性接入** — 只补 Token 计数 |

### 12. guardrails/ — 安全护栏

| 属性 | 值 |
|------|-----|
| **API** | `GuardrailProvider` → 内置护栏（shell injection 检测等）|
| **功能** | 输入/输出安全过滤 |
| **已用** | ❌ 未用 |
| **推荐** | ❌ **不推荐** — 证明工作流不涉及用户输入 |

### 13. reflection/ — 反射工具

| 属性 | 值 |
|------|-----|
| **API** | `resolve_class("pkg.module:ClassName", base_class)` |
| **功能** | 字符串→Python 类反射解析。`create_deerflow_agent`、`get_sandbox_provider` 等内部使用 |
| **已用** | ✅ 隐含使用（通过 `get_app_config()` 间接） |
| **推荐** | 无需直接使用 |

---

## 接入状态汇总

| 模块 | 状态 | 优先级 |
|:----:|:----:|:------:|
| `models/` | ✅ 完全接入 | — |
| `tools/` | ✅ 完全接入 | — |
| `mcp/` | ✅ 完全接入 | — |
| `sandbox/` | ✅ 已接入（可加深） | 🟢 低 |
| `skills/` | ✅ 已接入 | — |
| `config/` | ✅ 部分接入 | — |
| **`runtime/checkpointer/`** | ❌ 未接入 | 🔴 **建议接入** |
| `runtime/events/` | ❌ 未接入 | 🟢 低 |
| `subagents/` | ❌ 不推荐 | — |
| `persistence/` | ❌ 不推荐 | — |
| `agents/` (中间件) | ❌ 选择性补 | 🟡 中 |
| `guardrails/` | ❌ 不推荐 | — |
| `uploads/` | ❌ 不推荐 | — |
| `tracing/` | ❌ 不推荐 | — |

---

## 具体行动项

| # | 模块 | 具体改动 | 文件 | 工作量 |
|:-:|:----:|----------|:----:|:------:|
| 1 | checkpointer | `w.compile(checkpointer=MemorySaver())` | archon_graph.py + unified_graph.py | 0.2h |
| 2 | sandbox | `sandbox.grep()` 替代 `_bash("grep ...")` | archon_graph.py + unified_graph.py | 0.3h |
| 3 | 中间件 | `_safe_invoke()` 调用前后加 token 计数 | archon_graph.py + unified_graph.py | 0.3h |

总共 **0.8 小时**，完成后 DeerFlow 基础设施接入度从 ~60% 提升到 ~85%。
