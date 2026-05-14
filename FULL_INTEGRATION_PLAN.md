# 全面使用 DeerFlow 基础设施 — 可行性分析

> 是否可以将整个 archon 工作流完全建立在 DeerFlow 的调度能力之上？

---

## 一、核心矛盾回顾

```
DeerFlow 的调度模型:                 我们的工作流：
                                   
lead_agent                            plan→prove→review 三阶段
├── create_agent()                    ├── planner（设定目标）
│   model → tools → model → tools     ├── prover（填充证明）
│   （平面循环）                       ├── reviewer（编译验证）
└── 自动中间件链                       └── review_agent（记录）
                                      每个节点做的事情完全不同
```

**create_agent() 的平面循环无法表达三阶段= 之前的结论不变。** 但"全面使用 DeerFlow 基础设施"不等于"用 create_agent 替换 StateGraph"。

---

## 二、可行方案：层级分离架构

```
Layer 1: 编排层（我们的代码，控制流程）
─────────────────────────────────────────
StateGraph: planner → prover → reviewer → review_agent → (loop)
  控制"什么时候做什么"，用条件路由决定下一阶段。
  这一层不调 LLM，只调下一层的 agent。

Layer 2: 执行层（DeerFlow agent，处理具体任务）
─────────────────────────────────────────
prover 阶段内部:
  for f in pending:
      agent = create_deerflow_agent(
          model=...,
          tools=get_available_tools(),   ← 34 个工具
          middleware=middleware_chain,    ← 全中间件
          checkpointer=MemorySaver(),    ← Checkpoint
      )
      result = agent.invoke(...)
      # agent 内部: LLM 思考 → 调 sandbox → 调 LSP → 编译验证

review_agent 阶段内部:
  review_agent(state)          ← 纯逻辑，不调 LLM

planner 阶段内部:
  planner(state)               ← 纯逻辑，不调 LLM
```

**编排层控制"流程顺序"，执行层发挥"AI 能力"。**

---

## 三、这个方案为什么行

因为我们的三阶段循环中，真正需要 DeerFlow 基础设施的只有 **prover 阶段**：

| 阶段 | 所需 DeerFlow 能力 | 是否需要 agent |
|:----:|-------------------|:--------------:|
| planner | 无 — 纯逻辑（扫描 + 分析失败模式） | ❌ |
| prover | **全部**：sandbox、LSP 工具、中间件、checkpoint | ✅ |
| reviewer | 无 — `lake build` + 统计 | ❌ |
| review_agent | 无 — 写 journal 文件 | ❌ |

所以实际的改法很聚焦：**只把 prover 节点改成 `create_deerflow_agent()`**，其他三个节点保持纯 Python 逻辑。

---

## 四、具体架构

```python
def prover(state: ArchonState) -> ArchonState:
    """prover 节点使用 DeerFlow 完整基础设施。"""
    ws = state["workspace_path"]
    pending = state.get("pending", [])
    
    for t in pending:
        # 1. 先试自动化策略级联（纯代码，不调 agent）
        cascade_ok, tactics = _try_tactics_cascade_all(ws, f)
        if cascade_ok:
            state["completed"].append(f)
            continue

        # 2. 创建 DeerFlow agent 来证明这个文件
        agent = create_deerflow_agent(
            model=create_chat_model(_get_model_name()),
            tools=get_available_tools(),        # 34 工具
            system_prompt=_build_prove_prompt(f, state),
            features=RuntimeFeatures(
                sandbox=True,                    # ✅ 自动 sandbox
                token_usage=True,                # ✅ 自动计数
            ),
            checkpointer=MemorySaver(),          # ✅ 自动 checkpoint
            name=f"prove-{Path(f).stem}",
        )
        
        # agent 内部自动处理：
        #   LLM 思考 → 调 lean_goal(目标) → 写代码 → 调 lean_verify → 失败→重试
        #   所有工具调用经 middleware 链 → sandbox → LSP
        
        result = agent.invoke({
            "messages": [HumanMessage(content=f"填充 {f} 中的 sorry")]
        })
        
        # 3. 合并结果
        state["attempt_history"].append(...)
```

**agent 内部自动获得的 DeerFlow 能力：**

| 能力 | 当前手动实现 | agent 自动获得 |
|------|------------|:-------------:|
| 工具绑定 | `_safe_invoke()` → `model.bind_tools()` | ✅ `create_agent(tools=...)` |
| Tool call loop | `_safe_invoke()` 手动循环（≤3 轮） | ✅ 自动无限循环 |
| Sandbox 文件 I/O | `_read()`/`_write()` → sandbox fallback | ✅ SandboxMiddleware 自动注入 |
| Sandbox bash | `_bash()` → sandbox fallback | ✅ agent 调 sandbox bash 工具 |
| Token 计数 | ❌ 无 | ✅ TokenUsageMiddleware |
| Checkpoint | ❌ 无 | ✅ MemorySaver |
| 死循环检测 | `loop_count < max_loops` | ✅ LoopDetectionMiddleware |
| 工具异常处理 | try/except | ✅ ToolErrorHandlingMiddleware |
| 错误结构 | `_parse_lean_errors()` | 仍需保留（Lean 特有） |
| LSP 工具 | `_safe_invoke()` + MCP | ✅ MCP 工具自动在 tool list 中 |

---

## 五、改造工作流（具体改法）

### 改前

```
prover():
  for f in pending:
    _try_tactics_cascade_all()    ← 纯代码
    _safe_invoke()                ← 手动 tool loop + bind
    _verify_file()                ← _bash("lake env lean")
    _parse_lean_errors()          ← 解析错误
```

### 改后

```
prover():
  for f in pending:
    _try_tactics_cascade_all()    ← 纯代码（保留）
    
    agent = create_deerflow_agent(
      model=...,
      tools=get_available_tools(),       # 含 sandbox + MCP + builtin
      features=RuntimeFeatures(
          sandbox=True,
          token_usage=True,
      ),
      checkpointer=MemorySaver(),
      system_prompt=_build_prove_prompt(f),
    )
    
    result = agent.invoke({
        "messages": [HumanMessage(content=f"填充 {f} 中的 sorry 并编译验证")]
    })
    
    # agent 内部自动：
    #   1. 读取文件 → lean_goal 获取目标 → 搜索引理 → 写证明代码
    #   2. 编译验证 → 失败→重试
    #   3. 通过后返回
```

### 需要保留的自定义代码

| 代码 | 原因 |
|------|------|
| `_try_tactics_cascade_all()` | 纯 Lean 操作，不经过 LLM |
| `_parse_lean_errors()` | Lean 特有错误格式解析 |
| `_extract_goal()` | 目标提取（给 planner 用） |
| `_classify_failure()` | 失败模式分类（给 planner 用） |
| `_local_lean_search()` | 本地搜索（LSP 可能慢或不可用时的回退） |
| plannner / reviewer / review_agent | 纯逻辑节点，不需要 agent |
| `_make_attempt()` | attempt 记录格式 |
| review_agent 的 journal 写入 | 结构化日志 |

### 可以删除/简化的代码

| 代码 | 替代 |
|------|------|
| `_safe_invoke()` 的 tool loop | `create_agent()` 自动处理 |
| `_bash()` 中 sandbox fallback | agent 直接调 sandbox bash 工具 |
| `_read()`/`_write()` sandbox fallback | agent 直接调 sandbox read/write 工具 |
| `_verify_file()` | agent 直接调 `lean_verify` LSP 工具 |
| `_get_all_tools()` | `get_available_tools()` |
| `_DEFAULT_SKILL` 手动注入 | `apply_prompt_template()` 自动注入 |

---

## 六、可行性结论

**可以，但只改 prover 一个节点。** 不是"全面替换 StateGraph"，而是在 StateGraph 的 prover 节点内部，用 `create_deerflow_agent()` 替代 `_safe_invoke()`。

| 维度 | 评估 |
|:----:|------|
| 技术可行性 | ✅ **可行** — `create_deerflow_agent()` 已经封装好了所需能力 |
| 改造范围 | 🟡 **聚焦** — 只改 prover 一个节点，其他 3 个节点不动 |
| 代码删除 | **~100 行** — `_safe_invoke()`、`_get_all_tools()`、`_bash()` sandbox 逻辑 |
| 代码保留 | **~300 行** — 级联策略、错误解析、planner、reviewer、review_agent |
| 新增代码 | **~50 行** — `_build_prove_prompt()`、`create_deerflow_agent()` 调用 |
| 总工作量 | **~1 小时** |
| 风险 | 🟢 低 — prover 节点可先双轨运行（新 agent + 旧 fallback）|
