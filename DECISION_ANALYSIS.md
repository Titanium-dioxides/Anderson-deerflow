# 架构决策分析: 手动 StateGraph vs create_agent()

> Y1 剩余唯一未决架构问题。此文件分析两者利弊，不做最终决定。

---

## 一、两套架构

### 方案 A: 手动 StateGraph (当前)

```python
# 自己构建图
w = StateGraph(ArchonState)
w.add_node("planner", planner)
w.add_node("prover", prover)
w.set_entry_point("planner")

# 自己处理状态
class ArchonState(dict):
    workspace_path: str
    pending: list
    attempt_history: list
    ...

# 自己管理工具
def _bash(cmd, cwd): ...
def _safe_invoke(messages): ...
```

### 方案 B: create_agent() (DeerFlow 标准)

```python
# DeerFlow 帮你构建图
return create_agent(
    model=create_chat_model(name),
    tools=get_available_tools(),
    middleware=middleware_chain,
    system_prompt=apply_prompt_template(...),
    state_schema=ThreadState,
)
```

---

## 二、多维度对比

### 2.1 工作流灵活性

| 维度 | 手动 StateGraph (当前) | create_agent() |
|------|:---------------------:|:--------------:|
| 节点结构 | **任意**：4 个自定义节点，每个可含分支逻辑 | 固定为 `model → tools → model → tools → ...` 循环 |
| 状态流转 | **完全控制**：planner 可设 stage，prover 可检查，reviewer 可路由 | `AgentState(messages)` + 自定义字段（通过 `extra`） |
| 非标准循环 | **原生支持**：prover→reviewer→planner 三阶段循环 | **不支持**：单次 agent 执行无法做多阶段循环 |
| 子图嵌套 | **可以**：可在 prover 节点中嵌入子图 | 不支持：agent 是平面的 |

**结论：create_agent() 不支持 plan→prove→review 这种结构化多阶段循环。** 它只能做"LLM 思考 → 调工具 → 回结果 → LLM 再思考"的单阶段循环。我们的三个节点之间的状态路由逻辑（`route()` 函数），在 create_agent 模式下没有对应机制。

### 2.2 工具管理

| 维度 | 手动 StateGraph (当前) | create_agent() |
|------|:---------------------:|:--------------:|
| 工具来源 | `_get_all_tools()` → `get_available_tools()` | `get_available_tools()` ✅ **原生** |
| 工具绑定 | `_safe_invoke()` → `model.bind_tools(tools)` | `create_agent(tools=...)` ✅ **自动** |
| Tool calling loop | `_safe_invoke()` 手动实现（≤3轮） | **自动**：create_agent 内置无限工具循环 |
| MCP 工具 | ✅ **通过 deerflow.mcp 获得** | ✅ **通过同一管道获得** |
| Skill tool policy | ❌ 未使用 `filter_tools_by_skill_allowed_tools` | ✅ **自动应用** |

**结论：create_agent() 的工具管理更优雅。** 但当前手动实现已经通过 `_safe_invoke()` 解决了核心需求。

### 2.3 中间件（Middleware）

| 中间件 | 作用 | 手动 StateGraph | create_agent() |
|--------|------|:--------------:|:--------------:|
| ThreadDataMiddleware | 创建工作区目录 | ❌ 手动管理 | ✅ 自动 |
| SandboxMiddleware | 获取 sandbox 实例 | ❌ 自建 fallback | ✅ 自动 |
| SummarizationMiddleware | 上下文压缩 | ❌ 无 | ✅ 自动 |
| TitleMiddleware | 对话标题 | ❌ 无（对话模式） | ✅ 自动 |
| MemoryMiddleware | 长期记忆 | ❌ 无 | ✅ 自动 |
| TokenUsageMiddleware | Token 计数 | ❌ 无 | ✅ 自动 |
| ToolErrorHandlingMiddleware | 工具异常→ToolMessage | ❌ try/except | ✅ 自动转换 |
| LoopDetectionMiddleware | 死循环检测 | ❌ 无 | ✅ 自动 |

**结论：这是 create_agent() 最大的优势。7 个中间件等于 7 个我们没写的功能。**

### 2.4 状态与持久化

| 维度 | ArchonState (当前) | ThreadState (create_agent) |
|------|:------------------:|:--------------------------:|
| 基类 | `dict` | `AgentState` (LangGraph 内置) |
| 消息持久化 | ❌ 无 | ✅ LangGraph 自动 checkpoint |
| Sandbox 路径 | ❌ 手动拼接 | ✅ `thread_data` 字段自动管理 |
| 自定义字段 | ✅ 完全自由 | ✅ `.extra` 字段可扩展 |
| 序列化 | ❌ 无 | ✅ LangGraph 原生支持 |

**结论：ThreadState 有消息持久化和 checkpoint，但我们的自定义字段（pending/completed/attempt_history/failure_modes 等 12 个）需要全部塞进 `.extra`。**

### 2.5 变更规模

| 维度 | 手动 StateGraph | create_agent() |
|------|:--------------:|:--------------:|
| 需修改的文件数 | — | archon_graph.py, unified_graph.py (核心) |
| 需删除的代码 | — | planner/reviewer/review_agent 三个节点、route()、fresh_state() |
| 需新增的代码 | — | agent 配置、状态转换逻辑、中间件选择 |
| 需保留的代码 | — | prover 中 `_prove_single_file()`、`_prove_with_reasoner()`、所有工具函数 |
| 工作流表达 | — | **需要重新设计"plan→prove→review 循环"在平面 agent 中的表达方式** |

---

## 三、关键的不可行问题

### create_agent() 无法直接表达三阶段循环

我们的工作流是：

```
planner (设定目标) → prover (填充证明) → reviewer (编译验证) → review_agent (记录)
    ↑                                                                  │
    └────────────────────────── COMPLETE? ─────────────────────────────┘
```

create_agent() 的循环是：

```
model (思考) → tools (执行) → model (思考) → tools (执行) → ... → 结束
```

**无法直接映射。** 要做三阶段循环，create_agent 需要：

1. 把所有逻辑压缩到 system prompt 中，让 LLM 自己决策"现在该 plan / prove / review"
2. 用工具调用模拟阶段切换（如 `planner_tool`、`prover_tool`、`reviewer_tool`）
3. 无法保证执行顺序——LLM 可能跳过 review 直接结束

### 手动 StateGraph 能表达但 create_agent 不能的关键模式

```python
# 三阶段循环：目前 15 行代码
def route(state):
    if state["stage"] == "COMPLETE": return END
    return "review_agent"  # 必须先审查再循环

w.add_edge("review_agent", "planner")  # 审查→重新规划

# Prover 内部并行：30 行代码
for t in pending:
    futures.append(executor.submit(_prove_single_file, ...))
```

在 create_agent 中，这些需要额外来实现：
- 阶段路由 → 需要 system prompt 约束 + 工具命名约定
- 并行证明 → 需要 subagent 系统（额外复杂度）

---

## 四、结论

| 维度 | 手动 StateGraph | create_agent() | 权重 |
|------|:--------------:|:--------------:|:----:|
| 工作流灵活性 | ✅ **适合** | ❌ 不适合结构化工作流 | 🔴 高 |
| 工具管理 | ✅ 已互补 | ✅ 原生支持 | 🟢 低 |
| 中间件 | ❌ 缺 7 个 | ✅ 全自动 | 🟡 中 |
| 状态持久化 | ❌ 无 checkpoint | ✅ 有 checkpoint | 🟡 中 |
| 变更成本 | — | 🔴 高：需要重构工作流表达 | 🔴 高 |

### 推荐：混合模式

**不要全面迁移到 create_agent()**，因为这会导致三阶段循环无法自然表达。但可以从 create_agent 中借鉴以下能力：

1. **保留手动 StateGraph 的结构**（planner→prover→reviewer→review_agent）
2. **在每个节点内部使用 `_safe_invoke()`**（已有，含工具绑定+重试）
3. **补关键中间件功能**（自行实现最少必需项）

具体路径：

| 缺失能力 | 补全方式 | 成本 |
|----------|----------|:----:|
| Sandbox 自动获取 | 图节点入口获取 sandbox（已开始做） | 0.5h |
| 上下文压缩 | 在 reviewer 后加入 token 计数和截断 | 1h |
| Checkpoint | LangGraph 内置，启用即可 | 0.2h |
| Memory | 非必需：证明工作流不需要长期记忆 | — |
| Token 计数 | 在 review_agent 中加统计 | 0.3h |
| 死循环检测 | 在 route() 中加入 loop_count 检查（已有） | 0h |
