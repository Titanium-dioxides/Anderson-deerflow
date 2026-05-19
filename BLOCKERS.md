# BLOCKERS.md — 受阻问题与根本原因分析

> 最后更新：2026-05-19
> 🔴 = 仍受阻 | ✅ = 已解决 | ⏳ = 未实现

## 快速状态

| Block | 原始分类 | 新分类 | 最终状态 |
|:-----:|:--------:|:------:|:--------:|
| B1 LSP 工具不可用 | 🚧 外部依赖 |   Architecture | ✅ MCP 工具通过 SubagentExecutor 自动可用 |
| B2 exact?/apply? 策略 | 🚧 外部依赖 | ⚡ 自动解除 | ✅ B1 解除后自动可用 |
| B3 无集成测试环境 | 🚧 无环境 | 🚧 无环境 | 🔴 需要 deer-flow 容器运行时 |
| B4 并行 Prover |   Architecture | ⚡ 架构可解决 | ✅ SubagentExecutor 并行 spawn |
| B5 子目标分解 | ⏳ 未实现 | ⏳ 未实现 | 🔴 纯 LLM 任务，未做 |
| B6 Review Agent 代码变更 | ⏳ 未实现 | ⏳ 未实现 | 🔴 需引入文件快照 diff |
| A1-A3 规范问题 | — | — | ✅ 2026-05-19 全部修复 |
| D1-D3 Subagent 问题 | — | — | ✅ 2026-05-19 全部修复 |
| E1-E6 代码质量 | — | — | ✅ 2026-05-19 全部修复 |

---



> 区分"暂时做不到"和"还没做"。每次解除一个 blocker 请记录。

---

## 一、分类方法

| 类别 | 标识 | 含义 | 示例 |
|:----:|:----:|------|------|
| 🚧 外部依赖 | Blocked | 依赖未满足的外部条件，无法在当前环境下实现 | 需要 Lean LSP 服务器 |
|   Architecture | Constraint | 当前架构设计限制，需重构才能支持 | LangGraph 纯函数模型与 MCP 协议不兼容 |
| ⏳ 未实现 | Not Done | 技术上可行，只是还没写 | 子目标分解、代码 diff |

---

## 二、受阻问题

### ✅ B1: Lean LSP 工具（已解决 2026-05-14）

**原始问题：** LSP 工具无法在纯 Python graph 节点中调用。
**解决方式：** prover 节点改用 `SubagentExecutor`，subagent 通过 `get_available_tools()` 自动获得 MCP 工具（含 lean_goal, lean_local_search 等 22 个 LSP 工具）。

---

**现状：** `extensions_config.json` 配置了 `lean-lsp-mcp` server，但它只对 DeerFlow agent runtime 暴露的 MCP 工具层生效。我们的 graph 节点（`planner()`、`prover()`）是原生 Python 函数，无法直接调用 MCP 工具。

**想做什么：**
```python
# 原版 Archon 的做法（LSP 实时查询）
goal = lean_goal("Basic.lean", 42)     # → "n : ℕ ⊢ n + 0 = n"
lemmas = lean_local_search("add_zero") # → ["add_zero", "add_zero"]
premises = lean_hammer_premise(...)    # → ["simp", "induction"]
```

**当前替代：** 文件扫描 `_extract_goal()` — 无法获取**编译时目标状态**（如 `h: a = b ⊢ a + 0 = b + 0`），只能获取源码级别声明签名。

**根本原因：** MCP（Model Context Protocol）是 LLM Agent 与工具之间的通信协议，LangGraph StateGraph 节点是纯 Python 函数，两者之间无天然桥梁。

```
  MCP Server (lean-lsp-mcp)        DeerFlow Agent Runtime       Graph Nodes
  ┌─────────────────────┐         ┌──────────────────┐       ┌──────────────┐
  │  JSON-RPC stdio     │◄────────│ tools: {...}     │       │ def prover() │
  │  lean_goal()        │  MCP    │ exposed via MCP  │   ??? │  # 纯Python  │
  │  lean_local_search()│────────►│ to LLM agent     │       │  # 无法调MCP │
  └─────────────────────┘         └──────────────────┘       └──────────────┘
```

**可行的桥接方式（都复杂）：**

| 方案 | 复杂度 | 描述 |
|:----:|:------:|------|
| A. 子进程 spawn | 中 | 在 `prover()` 节点中启动 lean-lsp-mcp 子进程，stdin/stdout JSON-RPC 通信。每个 prove 循环启动一次 |
| B. pre-computed 索引 | 低 | 不实时查询，而是在 planner 阶段扫描一次 mathlib 并缓存到状态中（不能获取 goal state） |
| C. 集成 DeerFlow agent runtime | 高 | 让 graph 节点通过 DeerFlow 的内部 agent API 调用 MCP 工具——这需要了解 DeerFlow 的内部架构 |

**推荐路径：** 方案 A（子进程 spawn）—— lean-lsp-mcp 已有完整的 Python 代码（`search_utils.py`、`client_utils.py`），可以 import 到 graph 节点中直接调用其函数，跳过 MCP 层。

---

### ✅ B2: exact?/apply? 策略（已解决 2026-05-14）

B1 解除后自动解决。`lean_hammer_premise` MCP 工具可用。

---

**现状：** `_AUTO_TACTICS` 当前为 `["rfl", "simp", "ring", "linarith", "omega", "aesop", "grind"]`，缺 `exact?` 和 `apply?`。

**原因：** `exact?` 和 `apply?` 在 Lean 中不是纯自动化策略——它们调用 LSP 查询 mathlib 搜索匹配当前目标的定理。写成 `by exact?` 可能超时（默认 3s 或更长）。

**直接写 `by exact?` 的问题：**
- 如果 LSP 未运行，`exact?` 会等待然后失败
- 超时时间不可控
- 在批量文件替换场景中，每个文件等待 3s 是不可接受的

**解决方案：** 禁用 `exact?` / `apply?` 的自动尝试，改为在 LLM prompt 中建议使用这些策略。或者等 B1 解决后用 LSP 调用替代。

---

### 🚧 B3: 无端到端集成测试环境（仍受阻）

**现状：** 冒烟测试只覆盖纯 Python 函数（L0-L2），无法验证完整工作流（L4）。

**需要的条件：**

| 依赖 | 状态 | 说明 |
|------|:----:|------|
| Python ≥ 3.12 | ✅ | 已安装 |
| `langgraph` | ❓ | 可能在 deer-flow 容器内 |
| `langchain-core` | ❓ | 同上 |
| `deerflow.models` | ❓ | 仅在 deer-flow 项目中 |
| Lean 4 + `lake` | ✅ | `~/.elan/bin` 可用 |
| 测试用 Lean 项目 | ✅ | `tests/fixtures/sample.lean` + `lakefile.toml` 需创建 |

**当前验证方式：** 纯函数单元测试 + 通过 `git diff` 手动审查代码逻辑。

**解除条件：** 在部署环境中（Docker 容器或完整 deer-flow 实例）运行集成测试。

---

### ✅ B4: 并行 Prover（已解决 2026-05-19）

通过 `SubagentExecutor.execute_async()` 实现每文件并行 spawn subagent。

---

**现状：** LangGraph StateGraph 节点串行执行，每个 sorry 逐一处理。

```
prover() 节点内部:
  for t in pending:    # 串行
    try_cascade(f)
    LLM(f)
    verify(f)
```

**LangGraph 的并行机制：** StateGraph 支持扇出（fan-out），但每个节点是操作**共享状态**的纯函数。如果两个 prover 同时修改同一文件的 `sorry`，会产生竞态。

```
planner → [prover_A → reviewer]  # 扇出两个 graph 分支
        → [prover_B → reviewer]  # 共享 workspace_path

问题: prover_A 写 Basic.lean, prover_B 同时写同一文件
     → 状态丢失或损坏
```

**可能的并行策略：**

| 策略 | 问题 |
|:----:|------|
| 每文件一个独立 LangGraph 实例 | 状态不共享，无法全局 review |
| 单节点内 `concurrent.futures` + 文件锁 | 简单可行，但 LangGraph 状态更新需序列化 |
| 分阶段：先规划 → 再并行证明 → 再合并审查 | 最安全，但架构改动大 |

**结论：** 技术上可行但需架构设计。目前串行模式对 <10 文件的项目足够。

---

### ⏳ B5: 子目标分解（未实现）

**为什么没做：** 时间/优先级。Planner 已经做了失败模式识别 + 目标提取 + 搜索，子目标分解是纯 LLM 任务在 planner prompt 中扩展。

**如何实现：** 在 planner 的 prompt 中加入：
```
如果一个 sorry 涉及多个独立论证步骤，请分解为辅助引理：
lemma helper_1 ... := by ...
lemma helper_2 ... := by ...
theorem main : ... := by
  ...使用 helper_1 和 helper_2...
```

然后在 planner 输出的结构中加入子目标字段。**技术上完全可行**，只是 scope 还没有 cover 到。

---

### ⏳ B6: Review Agent 缺少代码变更（未实现）

**为什么没做：** 需要引入每个 attempt 前后的文件快照比对。改动量约 20 行：

```python
# 在 prover() 中，LLM 调用前后做 diff
before = _read(ws, f)
# ... LLM 写 ...
after = _read(ws, f)
# diff = unified_diff(before, after)
state["attempt_history"][-1]["diff"] = diff
```

然后在 `review_agent` 中写入 journal。

**优先级低：** current journal 已经记录了 attempt 级别信息（strategy、result、error），diff 是增量改进。

---

## 三、Blocker 依赖树

```
B1 LSP 工具不可用
├── B2 exact?/apply? 策略 ───────────── 直接依赖 LSP
├── Review Agent 代码变更 ───────────── 独立（⏳ 未实现）
├── B4 并行 Prover ──────────────────── 独立（ 待设计）
└── Planner 子目标分解 ──────────────── 独立（⏳ 未实现）

B3 无集成测试环境
└── 验证任何 LangGraph 改动 ────────── 需要 deer-flow 运行时
```

最关键的 blocker：**B1（LSP 工具不可用）阻塞了 B2，但不阻塞其他路径。** 其余任务都可以在当前架构下独立推进。

---

## 四、勘误与更新

### 2026-05-14 勘误：B1 根因判断错误

**原始判断：** "MCP 协议与纯 Python 函数不兼容"
**实际：** DeerFlow 通过 `deerflow.mcp.tools.get_mcp_tools()` 将 MCP 工具暴露为 LangChain `BaseTool`，可以直接 `model.bind_tools()` 绑定到模型。

**重述 B1：** 不是"MCP 不可用"，而是"graph 节点架构需重构为 tool-calling loop 才能使用 MCP 工具"。

| 更新前 | 更新后 |
|--------|--------|
| 🚧 外部依赖：MCP 不兼容 |   Architecture：节点需改为 Agent 模式 |
| 方案：子进程 spawn | 方案：使用 `get_mcp_tools()` + `model.bind_tools()` + LangGraph `ToolNode` |
| 可行但复杂 | 标准 LangGraph 模式，但有工作量 |

### 影响

- B2（exact?/apply? 策略）现在也是   Architecture 约束，而非外部依赖
- 解除 B1 后 B2 自动解除（工具可用后，LLM 可自选使用 exact?/apply?）

---

## 五、DeerFlow 文档学习后的重新评估 (2026-05-14)

### DeerFlow 提供了什么

阅读 `README.md`、`ARCHITECTURE.md`、`MCP_SERVER.md` 以及源码后发现：

| 能力 | DeerFlow 支持 | 我们当前是否使用 |
|------|:-------------:|:----------------:|
| **MCP 工具加载** | `get_mcp_tools()` → `list[BaseTool]` | ❌ 手动 `_bash()` |
| **模型工具绑定** | `model.bind_tools()` + `create_agent()` | ❌ 直接 `model.invoke()` |
| **Sub-agents 并行** | `deerflow.subagents` 子代理系统 | ❌ 串行 for 循环 |
| **Sandbox 隔离** | Docker/Local sandbox provider | ❌ 直调 `subprocess` |
| **Skills 加载** | `skills/` → SKILL.md → SystemPrompt | ❌ 手动拼接 |
| **Checkpoint** | LangGraph 内置 | ❌ 无持久化 |

### 六个 blocker 的重新评估

#### B1: LSP 工具不可用 → 状态变更: 🚧 → ⚡ 可解决

**最新理解：** DeerFlow 的 `get_available_tools()` 已经集成了 MCP 工具（通过 `get_cached_mcp_tools()`）。我们只需要：

```python
from deerflow.tools import get_available_tools

tools = get_available_tools()  # 含 lean-lsp MCP tools
model = create_chat_model("deepseek-v4").bind_tools(tools)
```

`model.invoke()` 会自动处理工具调用，不需要手动 MCP 通信。

**根本原因（更新）：** 我们的 graph 节点设计为纯 Python 函数模式，绕过了 DeerFlow 的标准 agent 工具系统。不是技术不可行，是需要架构调整。

**解除方案：**
- 方案 A（轻量）：在 prover 节点中调用 `get_available_tools()`，`.bind_tools()` 到模型，然后调 `model.invoke()`。模型会自动决定是否调用 LSP MCP 工具
- 方案 B（标准）：改用 `create_agent()` 或 LangGraph 的 `ToolNode` 模式

#### B2: exact?/apply? 策略缺失 → 状态变更: 🚧 → ⚡ 自动解除

B1 解决后，LLM 可以自行在证明过程中调用 `lean_hammer_premise`（通过 LSP MCP）来查找匹配的引理，然后用 `exact` 或 `apply` 完成证明。**不需要手动实现。**

#### B3: 无集成测试环境 → 状态: 🚧

在容器外无法运行完整 deerflow 测试。这是硬依赖。

#### B4: 并行 Prover → 状态变更: 🚧 → ⚡ 可解决

**最新理解：** DeerFlow 自带 `deerflow.subagents` 系统，支持 spawn 子 agent 并行工作。这比手动 `concurrent.futures` 更优雅。

```python
from deerflow.subagents import spawn_subagent

# 每个文件 spawn 一个子 agent 去证明
futures = [spawn_subagent(f"prove_{f}", prover_task) for f in files]
results = await asyncio.gather(futures)
```

**根本原因：** 之前不知道 `subagents` 模块的存在。现在知道后，并行化是可行的。

#### B5: 子目标分解 → 状态: ⏳ 未实现（不变）

纯 LLM 任务，时间优先级问题。

#### B6: Review Agent 代码变更 → 状态: ⏳ 未实现（不变）

纯编码任务，改动量小。

### 总结

| # | 之前分类 | 新分类 | 原因 |
|:-:|:--------:|:------:|------|
| B1 | 🚧 外部依赖 | ⚡ **架构可解决** | `get_available_tools()` 已集成 MCP，直接调用即可 |
| B2 | 🚧 外部依赖 | ⚡ **自动解除** | B1 解决后 LLM 可自选使用 exact/apply |
| B3 | 🚧 无环境 | 🚧 **无环境** | 需要 deer-flow 容器运行时 |
| B4 |  约束 | ⚡ **架构可解决** | `deerflow.subagents` 支持并行 |
| B5 | ⏳ 未实现 | ⏳ **未实现** | 纯 LLM 任务 |
| B6 | ⏳ 未实现 | ⏳ **未实现** | 纯编码任务 |

之前说 3 个 🚧，实际上其中 2 个是对 DeerFlow 能力不了解导致的误判。现在只剩下 B3 是真正的 blocker。
