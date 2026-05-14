# KNOWLEDGE.md — 项目知识来源与应用记录

> 来源于原版 Archon、Rethlas、DeerFlow 三个项目的逆向分析与文档学习。
> 每有一条新知识被应用到项目中，在此记录。

---

## 知识来源

| 来源 | 位置 | 类型 |
|:----:|------|:----:|
| **Archon** | `/home/zdzdhd/ai4math/Archon` | 原始 Lean4 形式化证明 Agent 系统（Claude Code） |
| **Rethlas** | `/home/zdzdhd/ai4math/Rethlas` | 非形式化数学证明生成+验证 Agent 系统（Codex CLI） |
| **DeerFlow** | `/home/zdzdhd/deer-flow` | 底层框架（LangGraph + MCP + Sandbox + Sub-agents） |
| **DeerFlow 文档** | `README.md`, `ARCHITECTURE.md`, `MCP_SERVER.md` | 官方架构设计文档 |
| **DeerFlow 源码** | `backend/packages/harness/deerflow/` | 运行时实现参考 |

---

## 知识条目

### K001: plan→prover→reviewer 三阶段循环

- **来源:** Archon
- **文件:** `.archon-src/prompts/plan.md`, `prover-prover.md`, `review.md`
- **内容:** 原版 Archon 的核心工作流。Plan Agent 负责设置目标、分析失败模式、生成非形式化指引；Prover Agent 负责填充 sorry；Review Agent 负责审查日志、生成期刊和推荐。
- **应用:** `archon_graph.py` 的 `planner()` → `prover()` → `reviewer()` → `review_agent()` 四节点 StateGraph
- **移植状态:** 核心结构 100% 保留，Plan Agent 的子目标分解能力未完全移植

### K002: Lean4 语言 LSP 工具集

- **来源:** Archon `skills/lean4/`
- **文件:** `SKILL.md`（`/lean4:prove`, `/lean4:autoprove` 等命令）, `references/lean-lsp-tools-api.md`
- **内容:** 22 个 LSP 工具：`lean_goal`（精确目标）, `lean_local_search`（本地声明搜索）, `lean_leansearch`（语义搜索）, `lean_hammer_premise`（前提建议）, `lean_multi_attempt`（批量策略测试）, `lean_diagnostic_messages`（即时错误）等。
- **应用:** 通过 `deerflow.mcp.cache.get_cached_mcp_tools()` 加载，`_safe_invoke()` 绑定到 LLM
- **移植状态:** ✅ 全部 22 个工具可用

### K003: 自动化策略级联

- **来源:** Archon `references/tactics-reference.md`
- **内容:** 尝试自动化策略的顺序：`rfl → simp → ring → linarith → nlinarith → omega → exact? → apply? → grind → aesop`
- **应用:** `_AUTO_TACTICS = ["rfl", "simp", "ring", "linarith", "omega", "aesop", "grind"]`
- **移植状态:** 7/9 策略（缺 `exact?` / `apply?`, 依赖 LSP hammer premise, 已通过 B1/B2 修复解决）

### K004: 失败模式分类

- **来源:** Archon `plan.md`
- **内容:** 原版 Plan Agent 识别的四种失败模式：(1) Missing Infrastructure（Mathlib 缺少所需设施）, (2) Wrong Construction（基于错误构造的证明）, (3) Not Using Web Search（未搜索外部资源）, (4) Early Stopping（过早放弃）
- **应用:** `_FAILURE_KEYWORDS` 关键字匹配扩展为 5 种：`missing_infrastructure`, `typeclass`, `wrong_construction`, `early_stopping`, `compilation_error`
- **移植状态:** ✅ 完全移植，且比原版多识别一种 `typeclass`

### K005: Attempt 历史跟踪

- **来源:** Archon `prover-prover.md` `task_results/<file>.md` 日志格式
- **内容:** 每次证明尝试记录 strategy、result（RESOLVED/FAILED/IN PROGRESS）、lean_error、dead-end warnings、next steps
- **应用:** `attempt_history` 列表，每项含 `{file, line, strategy, result, lean_error, failure_mode, loop}`
- **移植状态:** ✅ 结构一致

### K006: 审查期刊（Review Agent）

- **来源:** Archon `review.md`
- **文件:** `proof-journal/sessions/session_N/summary.md`, `milestones.jsonl`, `recommendations.md`
- **内容:** Review Agent 读取 prover 日志 → 按文件分组 attempt → 生成 JSONL 里程碑 + 摘要 + 推荐。里程碑含 `{timestamp, status, target, session, findings, attempts[], next_steps}`。
- **应用:** `review_agent()` 节点写入 `{ws}/.archon-journal/session_N/{summary.md, milestones.jsonl, recommendations.md, PROJECT_STATUS.md}`
- **移植状态:** ✅ 结构一致，但缺少原版的逐 attempt 代码变更记录（old_text→new_text）

### K007: Lean 编译器错误结构化解析

- **来源:** Archon `references/compilation-errors.md`, `parse_lean_errors.py`
- **内容:** Lean 错误格式 `file:line:col: error: <type>` → 分类为 type_mismatch / unknown_identifier / failed_to_synthesize / ...
- **应用:** `_parse_lean_errors()` + `_classify_error()` 共 10 种分类
- **移植状态:** ✅ 完全移植

### K008: 增量编译

- **来源:** Archon `prover-prover.md` 三级验证阶梯（per-edit `lean_diagnostic_messages` → file gate `lake env lean` → project gate `lake build`）
- **内容:** `lake env lean <file>` 单文件增量编译（~1-2s）替代全量 `lake build`（~5-30s）
- **应用:** `_verify_file(ws, f)` 调用 `lake env lean`
- **移植状态:** ✅ 完全移植

### K009: Rethlas 非形式化证明生成与验证闭环

- **来源:** Rethlas `agents/generation/AGENTS.md`, `agents/verification/AGENTS.md`
- **内容:** 生成 Agent 有 10 个自适应推理 Skills（搜索、构造反例、子目标分解、直接证明、递归证明……），验证 Agent 有 3 个验证技能（顺序语句检查、外部引用验证、综合报告）。输出 `<proof>` 标签 + JSON verdict。
- **应用:** `unified_graph.py` 的 `generator_node()` + `verifier_node()` + `failure_report_node()`
- **移植状态:** 循环结构保留，10 个自适应 Skills 压缩为单一 prompt 中的策略框架

### K010: DeerFlow MCP 工具系统

- **来源:** DeerFlow `backend/docs/MCP_SERVER.md`, `backend/packages/harness/deerflow/mcp/tools.py`, `cache.py`
- **内容:** `get_cached_mcp_tools()` 返回 `list[BaseTool]`（LangChain 工具）。MCP 服务器在 `extensions_config.json` 中配置，支持 stdio/SSE/HTTP 传输。支持 OAuth 和工具拦截器。
- **应用:** `_get_all_tools()` 调用 `get_available_tools()`（含 MCP）
- **移植状态:** ✅ 完全接入

### K011: DeerFlow Sandbox 隔离层

- **来源:** DeerFlow `backend/docs/ARCHITECTURE.md`, `sandbox/sandbox.py`, `sandbox/local/local_sandbox_provider.py`
- **内容:** `SandboxProvider.acquire()` → `Sandbox.execute_command()` / `read_file()` / `write_file()`。本地模式（LocalSandboxProvider）直接运行，Docker 模式通过容器隔离。支持虚拟路径映射。
- **应用:** `_bash()` / `_read()` / `_write()` 先试 sandbox，失败回退到直接执行
- **移植状态:** ✅ 已整合，`_SANDBOX_AVAILABLE` 守卫

### K012: DeerFlow Skills 加载与注入

- **来源:** DeerFlow `skills/` 目录结构, `agents/lead_agent/prompt.py` `apply_prompt_template()`
- **内容:** `skills/{public,custom}/{name}/SKILL.md` → DeerFlow 自动加载 → 注入 agent system prompt。Skill 可声明 `allowed-tools` 白名单。
- **应用:** `_load_skill_content("archon-lean4")` 手动读取并注入 prover SystemMessage
- **移植状态:** ⚠️ 未使用 `apply_prompt_template()`（因为手动 StateGraph 不走 `create_agent()` 流程），改为手动注入

### K013: DeerFlow 多源工具聚合

- **来源:** DeerFlow `tools/tools.py` `get_available_tools()`
- **内容:** `get_available_tools()` 聚合三类工具：(1) builtin（present_file, ask_clarification）, (2) configured（sandbox bash/read_file/write_file/web_search）, (3) MCP（via `get_cached_mcp_tools()`）。支持 `groups` 过滤、model-aware 视觉工具开关、sandbox 安全策略。
- **应用:** `_get_all_tools()` → `get_available_tools()`（34 个工具）
- **移植状态:** ✅ 完全接入

### K014: DeerFlow ThreadPoolExecutor 安全

- **来源:** DeerFlow `mcp/tools.py` `_SYNC_TOOL_EXECUTOR`
- **内容:** DeerFlow 内部使用 `concurrent.futures.ThreadPoolExecutor(max_workers=10)` 来做同步包装异步工具。`atexit` 注册关闭钩子。
- **应用:** prover 节点 `ThreadPoolExecutor(max_workers=min(files, 4))`，timeout=300s
- **移植状态:** ✅ 遵循相同模式

### K015: deerflow.models.create_chat_model 抽象

- **来源:** DeerFlow `models/factory.py`
- **内容:** `create_chat_model(name, thinking_enabled)` 从 `config.yaml` 读取模型配置，通过 `resolve_class()` 反射创建 `BaseChatModel` 实例。支持 thinking 模式切换、超时配置。
- **应用:** `_model()` 和 `_safe_invoke()` 中统一调用
- **移植状态:** ✅ 完全使用

### K016: DeerFlow Lead Agent 架构模式

- **来源:** DeerFlow `ARCHITECTURE.md`, `agents/lead_agent/agent.py`
- **内容:** `lead_agent` 使用 `create_agent()` + middleware chain（SandboxMiddleware、SummarizationMiddleware、MemoryMiddleware 等）。工具通过 `get_available_tools()` 获取。System prompt 通过 `apply_prompt_template()` 自动注入 skills + memory。
- **应用:** 未使用。项目采用手动 `StateGraph` 模式以适应结构化定理证明工作流。
- **移植状态:** ❌ 未采用。这是 Y1 问题——已知架构权衡。

### K017: DeerFlow Sub-agents 并行执行

- **来源:** DeerFlow `subagents/executor.py`, `subagents/config.py`
- **内容:** `SubagentExecutor` 可 spawn 子 agent 执行独立任务。支持 per-subagent 的 `tools` 白名单、`skills` 白名单、`model` 独立配置、`max_turns` 和 `timeout_seconds` 保护。
- **应用:** 未使用。改用 `ThreadPoolExecutor` 做更轻量的文件级并行。
- **移植状态:** ❌ 未采用。`ThreadPoolExecutor` 更轻量，且不需要走完整的 subagent 创建流程。

### K018: Archon lean-lsp-mcp 服务器架构

- **来源:** Archon `.archon-src/tools/lean-lsp-mcp/`
- **文件:** `server.py`, `search_utils.py`, `client_utils.py`, `repl.py`, `verify.py`
- **内容:** `lean-lsp-mcp` 是一个独立的 MCP server，通过 stdio JSON-RPC 暴露 Lean LSP 能力。`search_utils.py` 使用 ripgrep 做本地搜索，`client_utils.py` 封装 LSP 客户端。
- **应用:** `extensions_config.json` 中配置为 MCP server，DeerFlow 自动加载
- **移植状态:** ✅ 完整保留，通过 MCP 集成

### K019: 项目开发准则

- **来源:** 本项目演进过程中确立的规范
- **应用:** `MIGRATION_LOG.md` 头部 6 条准则
- **内容:**
  1. 每次代码修改记录到 `MIGRATION_LOG.md`
  2. 每次修改后执行冒烟测试（规则见 `SMOKE_TEST.md`）
  3. 测试结果记录到 `SMOKE_TEST_LOG.md`
  4. 每次修改后 `git commit`
  5. 维护 `TODO.md`
  6. 维护 `BLOCKERS.md`
