# 架构决策分析: 手动 StateGraph vs create_agent()

> 剩余架构问题分析。基于 DeerFlow 框架层级的理解。

---

## 一、DeerFlow 的三个层级

```
Layer 1: Agent 层                  Layer 2: Graph 层          Layer 3: 基础设施层
                                                              
create_agent()                     StateGraph                 
├── model + tools                  ├── nodes                  ├── sandbox/sandbox_provider.py
├── middleware chain                ├── edges                  ├── mcp/cache.py
│   ├── SandboxMiddleware          ├── conditional_routes     ├── skills/storage/
│   ├── TokenUsageMiddleware       └── compile()              ├── models/factory.py
│   ├── MemoryMiddleware                                    ├── tools/tools.py
│   ├── SummarizationMiddleware                              └── persistence/checkpointer/
│   ├── ToolErrorHandlingMiddleware
│   ├── LoopDetectionMiddleware   create_deerflow_agent()
│   └── ...                          ├── 1 的便利性
└── checkpointer                    └── 3 的内部调用
```

**我们的项目：** 在 Layer 2（手动 `StateGraph`）上构建，也直接用了 Layer 3（sandbox、mcp、skills/storage），但跳过了 Layer 1（中间件链）。

---

## 二、"另一个层级"的思路

不是"把 Layer 2 改成 Layer 1"（代价是失去三阶段循环），而是**在 Layer 2 的结构内，加深对 Layer 3 的使用**。

```
当前:                             优化后:

Layer 2 (StateGraph)              Layer 2 (StateGraph) — 不变
├── planner — 纯逻辑               ├── planner
├── prover                          ├── prover
│   ├── _safe_invoke()             │   ├── _safe_invoke() + 这里可以嵌入子 agent
│   └── _bash() → sandbox          │   └── sandbox ✅
└── reviewer                       └── reviewer
                                        ├── checkpointer ✅ (新增)
Layer 3 (基础设施)                  │   └── token 计数 ✅ (新增)
├── sandbox ✅ 已有                 Layer 3 (基础设施) — 更深使用
├── mcp ✅ 已有                     ├── sandbox ✅
├── skills/storage ✅ 已有          ├── mcp ✅
└── —                               ├── skills/storage ✅
                                    ├── langgraph.checkpointer ✅
                                    └── 自定义 token counter
```

---

## 三、具体可以做什么

### 3.1 Checkpointer（半小时）

LangGraph 原生支持，把 checkpointer 插到 `compile()` 即可：

```python
from langgraph.checkpoint.memory import MemorySaver

graph = w.compile(checkpointer=MemorySaver())
```

这让我们获得：
- 每次节点执行后自动保存状态
- 失败时可从上次 checkpoint 恢复
- 所有 `ArchonState` 字段自动持久化

不用改架构，一行代码。

### 3.2 Token 计数（20分钟）

在 `review_agent` 节点中加：

```python
# 从 model.response_metadata 提取 token 使用量
for a in state["attempt_history"]:
    # 实际上 token 计数在每次 _safe_invoke 的 response 中
    pass
```

然后写入 journal 文件。

### 3.3 在 prover 内部嵌入子 agent（可选项）

`prover` 节点内部（不是替换整个 graph），可以创建 `create_deerflow_agent()` 来处理**单个文件的证明任务**。这样这个子 agent 能获得完整中间件链，而外层的三阶段循环保持不变：

```python
def prover(state):
    for f in pending:
        # 创建临时子 agent 来处理这个文件
        agent = create_deerflow_agent(
            model=create_chat_model(...),
            tools=get_available_tools(),
            system_prompt=build_prove_prompt(f),
        )
        result = agent.invoke(...)
        # 把结果合并回 ArchonState
```

这看起来复杂且收益不大。不如保持当前的 `_safe_invoke()`。

### 3.4 实践中不需要的功能

| 中间件 | 是否需要 | 原因 |
|--------|:--------:|------|
| SandboxMiddleware | ✅ 已替代 | 直接在 Layer 3 调 `get_sandbox_provider()` |
| TokenUsageMiddleware | 🟡 可以自己加 | 20 行代码 |
| MemoryMiddleware | ❌ 不需要 | 证明工作流不需要长期记忆 |
| TitleMiddleware | ❌ 不需要 | 对话模式下有用，工作流不需要 |
| SummarizationMiddleware | ❌ 不需要 | token 用量小，结构固定 |
| ToolErrorHandlingMiddleware | ✅ 已替代 | `_safe_invoke()` 自己处理了 |
| LoopDetectionMiddleware | ✅ 已有 | `loop_count < max_loops` |
| ClarificationMiddleware | ❌ 不需要 | 证明工作流不需要澄清 |

---

## 四、结论

不做 create_agent 迁移。**保持在 Layer 2 + Layer 3，但加深 Layer 3 使用：**

| 行动 | 收益 | 工作量 |
|------|------|:------:|
| 启用 checkpoint | 状态自动持久化，可恢复 | 0.2h |
| 加 token 计数 | 了解成本 | 0.3h |
| **现状已足够** | | |

Total remaining work: **0.5 小时**，不涉及架构变更。
