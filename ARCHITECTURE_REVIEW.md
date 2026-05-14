# ARCHITECTURE_REVIEW.md — DeerFlow 设计风格复盘

> 检查 archon-deerflow 项目是否符合 DeerFlow 的设计规范与能力利用情况

---

## 一、DeerFlow 标准架构模式

```
Lead Agent (create_agent)
├── config.yaml → 模型、工具组、sandbox 配置
├── extensions_config.json → MCP 服务器配置
├── skills/ → SKILL.md → 系统提示注入
│   (agent runtime 自动加载 skills)
├── get_available_tools()
│   ├── builtin (present_file, ask_clarification...)
│   ├── configured (bash, web_search, read_file...)
│   └── MCP (get_cached_mcp_tools() → BaseTool)
├── model.bind_tools(tools)
├── Sandbox (隔离执行)
│   ├── bash_tool → 容器内执行
│   ├── read_file / write_file → 虚拟路径映射
│   └── execute_command → 原子操作
├── Middleware Chain
│   ├── SandboxMiddleware → sandbox 获取/释放
│   ├── SummarizationMiddleware → 上下文压缩
│   ├── MemoryMiddleware → 长期记忆
│   └── ...
└── Sub-agents (deerflow.subagents)
    └── 并行子 agent 执行
```

---

## 二、我们的项目与之对比

### 红色：严重偏离

| # | 问题 | 我们的做法 | DeerFlow 做法 | 影响 |
|:-:|------|-----------|:-------------:|------|
| **R1** | **文件 I/O** | 直接 `pathlib.Path.write_text()` | `sandbox.write_file()` → 虚拟路径映射 | 在 Docker 环节中可能路径错乱，无隔离 |
| **R2** | **bash 执行** | 直接 `subprocess.run()` + 手动 PATH | `sandbox.bash_tool()` → 容器内安全执行 | 安全风险，无沙箱隔离 |
| **R3** | **Lean 编译** | 手动 `_bash("lake env lean ...")` | 应通过 `lean_diagnostic_messages` LSP 工具 + `lean_build` 工具 | 绕过 sandbox，直接宿主机 |
| **R4** | **Skills 未注册** | SKILL.md 复制到 overlay 目录，但从不被 DeerFlow skill loader 加载 | `skills/` 目录 → agent runtime 自动加载 → 注入系统提示 | 技能知识未被注入 agent 上下文 |

### 黄色：设计模式偏离

| # | 问题 | 我们的做法 | DeerFlow 做法 |
|:-:|------|-----------|:-------------:|
| **Y1** | **Graph 编写方式** | 手动 StateGraph + 纯 Python 节点 | `create_agent()` → 自动 tool-calling loop + middleware |
| **Y2** | **工具获取** | 手动 `_get_lsp_tools()` → `model.bind_tools()` | `get_available_tools()` → 统一管理所有工具源 |
| **Y3** | **模型使用** | 硬编码 `"deepseek-v4"` 模型名 | `config.yaml` → `create_chat_model(name)` 配置驱动 |
| **Y4** | **状态管理** | 自定义 `ArchonState(dict)` | 使用 `ThreadState(AgentState)` → 内置 checkpoint |
| **Y5** | **文件扫描** | `_bash("grep -rn sorry ...")` | LSP tool `lean_diagnostic_messages` + `lean_file_outline` |
| **Y6** | **错误处理** | try/except + print | middleware chain `ToolErrorHandlingMiddleware` |

### 绿色：能用但可以优化

| # | 问题 | 我们的做法 | DeerFlow 做法 |
|:-:|------|-----------|:-------------:|
| **G1** | **并行** | 串行 for 循环 | `deerflow.subagents` 并行子 agent |
| **G2** | **提示词注入** | 手动 `SystemMessage(content=...)` | `apply_prompt_template()` → 自动注入 skills + memory + tools |
| **G3** | **配置** | 路径常量硬编码 (`_RETHLAS_DIR = Path(__file__).parent...`) | `config.yaml` + `app_config` |
| **G4** | **图注册** | `overlay/backend/langgraph.json` 手动复制 | deer-flow 原生 `langgraph.json` + `make config` |

---

## 三、核心问题：我们的架构跳过了 DeerFlow 的 Agent 层

DeerFlow 的设计层级：

```
用户消息
    │
    ▼
Lead Agent (create_agent)    ←── 标准入口点
    │
    ├── Middleware Chain      ←── 自动执行的预处理/后处理
    │
    ├── Model + Tools        ←── get_available_tools() 统一管理
    │
    └── Sub-agents            ←── 并行子任务
                               
    ┌─────────────────────────────────────────────┐
    │  我们的做法：                                │
    │                                              │
    │  run_archon_workflow(ws)                     │
    │    → build_archon_graph()                    │
    │      → StateGraph(ArchonState)               │
    │        → planner() [自定义节点]              │
    │        → prover() [自定义节点 + 手动 tool]   │
    │        → reviewer() [自定义节点]             │
    │        → review_agent() [自定义节点]         │
    └─────────────────────────────────────────────┘
```

我们创建了与 DeerFlow 的 `lead_agent` 平行的另一个 Agent 系统。它们之间：
- ❌ 不共享 middleware
- ❌ 不共享 sandbox
- ❌ 不共享 tool 配置
- ❌ 不共享 skills 注入
- ❌ 不共享 checkpoint
- ✅ 共享 `create_chat_model()`

---

## 四、每项问题的技术债务修复成本

| # | 问题 | 修复成本 | 修复路径 |
|:-:|------|:--------:|----------|
| R1 | 直接文件 I/O | 🟢 低 | `sandbox.write_file()` 替代 `Path.write_text()` |
| R2 | 直接 subprocess | 🟢 低 | `sandbox.bash_tool()` 替代 `_bash()` |
| R3 | 手动 Lean 编译 | 🟡 中 | 逐步迁移到 LSP 工具：先 `lean_multi_attempt` → `lean_verify` |
| R4 | Skills 未注册 | 🟢 低 | 将 SKILL.md 放在 `deer-flow/skills/` 下即可自动加载 |
| Y1 | 手动 StateGraph | 🔴 高 | 需重构为 `create_agent()` + subagent 模式 |
| Y2 | 手动工具获取 | 🟢 低 | `get_available_tools()` 替代 `_get_lsp_tools()` |
| Y3 | 硬编码模型名 | 🟢 低 | 从 `app_config` 读取 |
| Y4 | 自定义状态 | 🔴 高 | 继承 `ThreadState` 并启用 checkpoint |
| Y5 | grep 扫描 | 🟡 中 | 逐步迁移到 LSP: `lean_file_outline` + `lean_diagnostic_messages` |
| Y6 | 手动错误处理 | 🟢 低 | 引入 middleware |
| G1 | 并行 | 🟡 中 | `spawn_subagent()` 替代串行 for |
| G2 | 提示词注入 | 🟢 低 | `apply_prompt_template()` |
| G3 | 硬编码路径 | 🟢 低 | 从 `app_config` 或环境变量读取 |
| G4 | 图注册 | 🟢 低 | 修改 `backend/langgraph.json` |

---

## 五、优先级建议

### 立即修复（R1-R4，影响正确性/安全性）

```
R1: sandbox 文件 I/O     → 估计 0.5h
R2: sandbox bash          → 估计 0.5h
R3: 逐步迁移 LSP          → 估计 1h (已经部分完成 B1/B2)
R4: skills 注册           → 估计 0.2h
```

### 中期重构（Y1-Y4，提升可维护性）

```
Y1: create_agent 模式     → 估计 4h（架构级改动）
Y2: get_available_tools() → 估计 0.5h
Y3: config 驱动模型       → 估计 0.2h
Y4: ThreadState 集成      → 估计 2h
Y5: LSP 替代 grep         → 估计 1h
Y6: middleware            → 估计 1h
```

### 长期优化（G1-G4，性能/体验）

```
G1: subagents 并行        → 估计 2h
G2: apply_prompt_template → 估计 0.5h
G3: 配置驱动路径          → 估计 0.2h
G4: 原生图注册            → 估计 0.2h
```

---

## 六、核心问题总结

**我们的项目本质上是在 DeerFlow 内部运行了一个独立的、与 DeerFlow 设计风格不同的子 Agent 系统。** 虽然功能上工作，但从架构角度看存在三个方面的不契合：

1. **安全与隔离**（R1-R2）—— 绕过 sandbox，直接操作宿主机文件系统和进程，在容器部署中有风险

2. **能力未充分利用**（R4, Y2, G2）—— DeerFlow 的 skills 系统、工具管理、提示词模板等能力都没有用上，自己做了一套平替

3. **可维护性**（Y1, Y4）—— 自定义状态管理 + 手动 StateGraph 导致无法利用 DeerFlow 的 middleware、checkpoint、memory 等横向能力

**最根本的决策问题：我们选择用 `StateGraph` 手动构建了一个"自定义 agent"，而不是使用 DeerFlow 的 `create_agent()` 来构建"DeerFlow 原生 agent"。** 后者会自动获得 tool-calling loop、middleware chain、sandbox isolation 等全部基础设施。

但 tradeoff 也是真实的：`create_agent()` 是为通用对话 agent 设计的，而我们需要一个高度定制化的数学定理证明工作流（plan→prove→review 循环、失败模式识别、目标分解等）。通用的 agent 模式不一定能直接表达这种结构化工作流。
