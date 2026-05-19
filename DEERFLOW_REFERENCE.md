# DeerFlow 规范实践参考源

> 搜集时间：2026-05-19
> 基准：DeerFlow `backend/packages/harness/deerflow/` 源码 v2026

## 重要发现：没有独立的 DeerFlow 参考项目

搜索引擎和 GitHub 上 **没有找到独立使用 DeerFlow 的第三方开源项目**。

DeerFlow 2.0（本机版本）是 ByteDance 在 2025-2026 年新发布的框架，设计了全新的架构。目前唯一使用 DeerFlow 2.0 SDK（`create_deerflow_agent`, `make_lead_agent`, `RuntimeFeatures`, `ThreadState` 等）的代码集中在 deer-flow 仓库内部：

- **DeerFlow 自带的 lead_agent** — 配置驱动，通过 `make_lead_agent()` 创建
- **archon-deerflow** — 这是我们自己的项目，是第一个 Custom workflow on DeerFlow
- **DeerFlow 官方测试** — `test_create_deerflow_agent.py` 等

这意味着 **archon-deerflow 本身就是最早期的 DeerFlow 参考项目之一**。审计中发现的 A1-A4 问题也正是这个原因的体现——没有成熟的第三方参考可以抄。

**规范实践只能从 DeerFlow 内部源码提炼：**

---

## 规范参考源（按推荐优先级排列）

### 1. `test_create_deerflow_agent.py`

**位置：** `/home/zdzdhd/deer-flow/backend/tests/test_create_deerflow_agent.py`
**类型：** SDK 入口测试（~350 行测试用例）
**推荐理由：** DeerFlow 团队写的官方测试，覆盖了 `create_deerflow_agent()` 的所有规范用法。无外部依赖（全部 mock）。

| 模式 | 测试编号 | 学什么 |
|------|:--------:|--------|
| 最小创建 | test 1 | `create_deerflow_agent(model)` — 只传模型 |
| 带工具 | test 2 | `create_deerflow_agent(model, tools=[...])` |
| 带 system_prompt | test 3 | 自定义系统提示 |
| 声明式特征 | test 4 | `RuntimeFeatures(sandbox=True, auto_title=True)` → 自动组装中间件链 |
| 全接管中间件 | test 5 | `create_deerflow_agent(model, middleware=[...])` — 自定义整条链 |
| 特征冲突防御 | test 6 | `middleware` 与 `features` 不能同时用 |
| Vision 工具注入 | test 7 | `RuntimeFeatures(vision=True)` 自动注入 `view_image` 工具 |
| Subagent 工具 | test 8 | `RuntimeFeatures(subagent=True)` 自动注入 `task` 工具 |
| 中间件顺序 | test 9 | `ClarificationMiddleware` 永远在最后 |
| RuntimeFeatures 默认值 | test 10 | `sandbox=True`, `loop_detection=True`, 其余 False |
| 工具去重 | test 11 | 同名工具只保留第一个（用户提供优先） |
| Sandbox 禁用 | test 12 | `sandbox=False` 去掉 3 个中间件 |
| Checkpointer | test 13 | `create_deerflow_agent(model, checkpointer=MemorySaver())` |
| 自定义中间件替换默认 | test 14 | `RuntimeFeatures(memory=MyMemoryMiddleware())` |
| 自定义 sandbox 替换组 | test 15 | 传入 AgentMiddleware 实例替换 ThreadData+Uploads+Sandbox |
| 自动错误处理 | test 16 | `ToolErrorHandlingMiddleware` 和 `DanglingToolCallMiddleware` 总是存在 |
| 无 features 模式 | test 17 | `features=None, middleware=[]` → 只有核心 |
| @Next 定位 | test 18-22 | 装饰器声明中间件在链中的位置 |
| @Prev 定位 | test 23-25 | 在锚点之前插入 |
| 交叉锚定 | test 26 | 两个外部中间件互相锚定 |
| 无锚点时插入位置 | test 27 | 未锚定的 extras 在 Clarification 之前 |
| 顺序保持 | test 28 | extrac 插入后原有中间件顺序不变 |
| 死循环检测默认链 | test 29 | `RuntimeFeatures(loop_detection=True)` |
| 死循环检测禁用 | test 30 | `RuntimeFeatures(loop_detection=False)` |
| Plan mode | test 31 | `plan_mode=True` 注入 TodoMiddleware |
| 全打开测试 | test 34-35 | 全部 8 个 features=True 时的完整链 |
| 全链顺序断言 | test 36 | 14 个中间件的精确顺序（关键参考） |

**test 36 的完整规范中间件链顺序：**

```python
[
    "ThreadDataMiddleware",           # [0] 初始化线程工作区
    "UploadsMiddleware",              # [1] 处理上传文件
    "SandboxMiddleware",              # [2] acquire 沙箱环境
    "DanglingToolCallMiddleware",     # [3] 修补断裂的 ToolMessage
    "ToolErrorHandlingMiddleware",    # [4] 工具异常→结构化 ToolMessage
    "SummarizationMiddleware",        # [5] 上下文压缩
    "TodoMiddleware",                 # [6] 任务追踪 (plan_mode)
    "TitleMiddleware",                # [7] 自动生成对话标题
    "MemoryMiddleware",               # [8] 长期记忆
    "ViewImageMiddleware",            # [9] 视觉模型图像处理
    "SubagentLimitMiddleware",        # [10] 子 agent 并发控制
    "LoopDetectionMiddleware",        # [11] 死循环检测
    "ask_clarification_tool",         # [12] 工具（由 ClarificationMiddleware 注入）
    "ClarificationMiddleware",        # [13] 澄清请求处理 — 永远最后
]
```

---

### 2. `agents/factory.py` — `create_deerflow_agent()` SDK

**位置：** `/home/zdzdhd/deer-flow/backend/packages/harness/deerflow/agents/factory.py`
**类型：** SDK 入口源码
**推荐理由：** 这是 DeerFlow 对外发布的 SDK 入口。纯参数驱动，不读配置文件。展示 `_assemble_from_features()` 的特征→中间件映射逻辑。

关键接口签名：
```python
def create_deerflow_agent(
    model: BaseChatModel,
    tools: list[BaseTool] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: list[AgentMiddleware] | None = None,
    features: RuntimeFeatures | None = None,
    extra_middleware: list[AgentMiddleware] | None = None,
    plan_mode: bool = False,
    state_schema: type | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    name: str = "default",
) -> CompiledStateGraph:
```

---

### 3. `test_create_deerflow_agent_live.py` — 端到端集成测试

**位置：** `/home/zdzdhd/deer-flow/backend/tests/test_create_deerflow_agent_live.py`
**类型：** 需要真实 LLM API key 的集成测试
**推荐理由：** 展示实际 LLM 调用的三种模式。

**模式 A — 最小 agent（无中间件）：**
```python
graph = create_deerflow_agent(model, features=None, middleware=[])
result = graph.invoke(
    {"messages": [("user", "Say exactly: pong")]},
    config={"configurable": {"thread_id": str(uuid.uuid4())}},
)
```

**模式 B — 带自定义工具：**
```python
@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

graph = create_deerflow_agent(model, tools=[add], middleware=[])
result = graph.invoke({
    "messages": [("user", "Use the add tool to compute 3 + 7.")]
}, config={...})
```

**模式 C — RuntimeFeatures 声明式（全自动中间件链）：**
```python
feat = RuntimeFeatures(sandbox=False, auto_title=False, memory=False)
graph = create_deerflow_agent(model, features=feat)
result = graph.invoke({"messages": [("user", "What is 2+2?")]}, config={...})
```

---

### 4. `agents/lead_agent/agent.py` — `make_lead_agent()` 生产级入口

**位置：** `/home/zdzdhd/deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py`
**类型：** 生产级 agent 工厂（~200 行核心）
**推荐理由：** 这是 DeerFlow 在生产环境中实际使用的主入口。展示了：
- 中间件链的精确构建顺序（含注释解释为什么某些中间件必须先后）
- 配置驱动的模型解析（`_resolve_model_name`）
- 自定义中间件注入点（`custom_middlewares` 参数）
- `apply_prompt_template()` 的用法（自动注入 skills + 内存 + 工具信息）
- 完整的 `get_available_tools()` 调用 + sanitization

关键代码架构：
```python
def _build_middlewares(config, model_name, agent_name, custom_middlewares, *, app_config):
    middlewares = build_lead_runtime_middlewares(...)
    middlewares.append(_create_summarization_middleware(...))
    middlewares.append(_create_todo_list_middleware(...))
    middlewares.append(TokenUsageMiddleware(...))
    middlewares.append(TitleMiddleware(...))
    middlewares.append(MemoryMiddleware(...))
    middlewares.append(ViewImageMiddleware(...))
    middlewares.append(SubagentLimitMiddleware(...))
    middlewares.append(LoopDetectionMiddleware(...))
    if custom_middlewares:
        middlewares.extend(custom_middlewares)
    middlewares.append(ClarificationMiddleware())  # 永远最后
    return middlewares
```

---

### 5. 自定义 Agent 的目录结构（agents/ API）

**位置：** `/home/zdzdhd/deer-flow/backend/app/gateway/routers/agents.py` + `config/agents_config.py`
**类型：** REST API + 配置解析
**推荐理由：** 展示如何用配置驱动方式定义自定义 agent。

**标准目录结构：**
```
agents/<name>/
├── config.yaml     # 模型、工具组、技能白名单
└── SOUL.md         # 行为描述（人格、防护栏）
```

**标准 config.yaml：**
```yaml
name: code-reviewer
description: 专业代码审查 agent
model: deepseek-v3
tool_groups: ["file:read", "bash"]
skills: ["lean4", "code-review"]
```

规范模式：**配置驱动创建**，而非代码硬编码。

---

### 6. Skills 系统（skills/custom/math-prover）

**位置：** `/home/zdzdhd/deer-flow/skills/custom/math-prover/SKILL.md`
**类型：** 自定义技能
**推荐理由：** 展示 DeerFlow 原生技能的标准结构，含 YAML 元数据头、自定义 prompt 文件夹、工具脚本。

```yaml
---
name: math-prover
display_name: Math Prover (Rethlas 移植)
description: 数学定理证明与自我验证闭环
tags: [math, prover, verification, rethras, proof]
---
```

技能通过 `apply_prompt_template()` 自动注入 agent system prompt。技能可以声明 `allowed-tools` 白名单。

---

## 相关源码文件一览

| 文件 | 大小 | 作用 |
|------|:----:|------|
| `agents/factory.py` | ~250 行 | **SDK 入口** — `create_deerflow_agent()` |
| `agents/features.py` | ~80 行 | **RuntimeFeatures** 数据类 + @Next/@Prev 装饰器 |
| `agents/thread_state.py` | ~40 行 | **ThreadState** 定义 + 4 个 Annotated reducer |
| `agents/lead_agent/agent.py` | ~200 行核心 | **生产级 agent 工厂** — `make_lead_agent()` |
| `tools/tools.py` | ~150 行核心 | **`get_available_tools()`** — 多源工具聚合 |
| `sandbox/tools.py` | ~800 行 | 标准 sandbox 工具实现（bash, read_file, write_file, grep, glob） |
| `sandbox/middleware.py` | — | SandboxMiddleware 生命周期管理 |
| `agents/middlewares/` | 14 个文件 | 每个中间件的独立实现 |
| `tests/test_create_deerflow_agent.py` | ~350 行 | **最重要的学习对象** |
| `tests/test_create_deerflow_agent_live.py` | ~100 行 | 端到端集成测试 |
| `tests/test_subagent_executor.py` | ~1200 行 | 子 agent 执行器测试 |
