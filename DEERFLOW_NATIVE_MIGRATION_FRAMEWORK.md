# DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md

## 文档目的

本文档定义 **Archon + Rethlas → DeerFlow** 的目标迁移规范。

该规范服务于以下目标：

1. **保留论文所体现的能力水平**
2. **尽可能复用 DeerFlow 的原生基础设施**
3. **避免重复实现运行时、工具层、文件管理层**
4. **以论文、原始实现、DeerFlow 基础设施三者为共同基线**

本文档不是“现状描述”，而是“目标实现规范”。

---

## 一、三套基线

迁移必须同时对齐以下三套基线。

### 1. 论文基线

原论文在 `source_paper.md:1`。

论文定义的目标能力包括：

- `Rethlas` 负责非形式化数学研究式探索
- `Archon` 负责 Lean 4 形式化与验证
- 两者协作完成端到端问题求解与形式化验证
- 尽量减少人工干预

论文中最关键的系统结构包括：

- `Rethlas = generation agent + verification agent`
- `Archon = Plan Agent + Lean Agent`
- `Archon = Scaffolding -> Proving -> Verification/Polish`
- 检索驱动：Matlas / LeanSearch / LSP / Web / References
- 跨 session memory 与 review

### 2. 原实现基线

原始代码基线来自：

- `Rethlas/agents/generation/AGENTS.md:1`
- `Rethlas/agents/verification/AGENTS.md:1`
- `Archon/archon-loop.sh:1`
- `Archon/.archon-src/prompts/plan.md:1`
- `Archon/.archon-src/prompts/prover-prover.md:1`
- `Archon/.archon-src/prompts/prover-autoformalize.md:1`
- `Archon/.archon-src/prompts/prover-polish.md:1`
- `Archon/.archon-src/prompts/review.md:1`
- `Archon/.archon-src/tools/informal_agent.py:1`

这些文件不是简单参考资料，而是迁移的行为基线。

### 3. DeerFlow 基线

DeerFlow 的基础设施基线来自：

- `deer-flow/backend/docs/ARCHITECTURE.md:1`
- `deer-flow/backend/docs/CONFIGURATION.md:1`
- `deer-flow/backend/docs/MCP_SERVER.md:1`
- `deer-flow/backend/docs/summarization.md:1`
- `deer-flow/backend/docs/plan_mode_usage.md:1`
- `deer-flow/backend/docs/rfc-create-deerflow-agent.md:1`
- `deer-flow/backend/CLAUDE.md:1`
- `deer-flow/README.md:574`

DeerFlow 在本项目中的角色是：

> **运行时基础设施提供者**

而不是：

> **替代论文工作流的通用 agent 模板**

---

## 二、总设计原则

### 原则 1：保留算法结构，替换运行时基础设施

迁移的目标不是：

- 用 DeerFlow 重写出一个“功能差不多”的系统

迁移的目标是：

- **在 DeerFlow runtime 上重建论文中的系统行为**

因此：

- **算法结构** 参考论文与原实现
- **运行时基础设施** 参考 DeerFlow

### 原则 2：DeerFlow 是 runtime，不是 proof strategy

DeerFlow 负责：

- agent runtime
- middleware
- sandbox
- files/workspace
- tools/MCP
- subagent execution
- checkpointing
- run events/history

DeerFlow 不负责定义：

- Rethlas 的探索策略
- Archon 的双代理 proving 机制
- proof decomposition 的数学逻辑

### 原则 3：不为原生化牺牲论文能力

若 DeerFlow 的通用模式与论文结构冲突，优先级应为：

1. 论文能力
2. 原实现行为
3. DeerFlow 风格一致性

也就是说：

- **不能为了更像 DeerFlow 而压平论文中的多阶段、多代理结构**

### 原则 4：避免平行基础设施

若 DeerFlow 已经提供成熟设施，则不应重复维护平行层：

- 工具聚合层
- 文件工作区层
- sandbox 生命周期
- token / loop / error handling
- checkpoint
- run history

但如果 DeerFlow 没有提供论文所需的领域层结构，则应保留自定义层：

- problem-specific memory
- proof review artifacts
- decomposition plans
- failure summaries

### 原则 5：领域工作流与 DeerFlow runtime 分层

推荐分层如下：

- **L0 — DeerFlow Runtime**
  - config
  - models
  - tools
  - MCP
  - sandbox
  - middleware
  - subagents
  - checkpointer
  - run event store

- **L1 — Workflow Orchestration**
  - unified graph
  - archon graph
  - stage routing
  - retry control
  - artifact routing

- **L2 — Domain Logic**
  - Rethlas skills
  - Archon planning
  - Lean proof search strategy
  - formalization decomposition
  - review heuristics

---

## 三、必须保留的论文级系统结构

以下结构属于论文能力本体，必须保留。

### A. Rethlas 双代理闭环

来源：

- `source_paper.md:82`
- `Rethlas/agents/generation/AGENTS.md:1`
- `Rethlas/agents/verification/AGENTS.md:1`

必须保留：

- generation agent
- verification agent
- generation → verification → repair 的迭代回路
- 最多若干轮自修复
- skill-driven adaptive control loop

禁止退化为：

- 一个 prompt 生成证明，另一个 prompt 评分

### B. Rethlas 的 skill 驱动数学探索

来源：

- `source_paper.md:84`
- `Rethlas/agents/generation/AGENTS.md:1`

必须保留的能力类型：

- immediate conclusions
- search
- examples
- counterexamples
- decomposition plans
- direct proving
- recursive proving
- identify failures
- verification-triggered repair

### C. Archon 的双代理结构

来源：

- `source_paper.md:335`
- `source_paper.md:367`
- `Archon/.archon-src/prompts/plan.md:1`
- `Archon/.archon-src/prompts/prover-prover.md:1`

必须保留：

- Plan Agent：总结、分解、策略调整、失败归纳
- Lean Agent：局部 formalization 执行
- 两者上下文隔离
- Lean Agent 卡住时由 Plan Agent 重路由

### D. Archon 三阶段流程

来源：

- `source_paper.md:335`
- `Archon/.archon-src/prompts/prover-autoformalize.md:1`
- `Archon/.archon-src/prompts/prover-polish.md:1`

必须保留：

1. Scaffolding
2. Proving
3. Verification / Polish

不能把它退化成：

- “读取 informal proof -> 一次性填所有 `sorry`”

### E. 跨 session review 与 persistent memory

来源：

- `source_paper.md:377`
- `source_paper.md:383`
- `Archon/.archon-src/prompts/review.md:1`

必须保留：

- session 边界总结
- 多轮失败趋势识别
- 防止重复走死路
- review 结果反馈回下一轮 plan

---

## 四、必须复用的 DeerFlow 基础设施

以下设施必须作为迁移的默认主路径。

### 1. DeerFlow 编排能力

参考：

- `deer-flow/backend/docs/ARCHITECTURE.md:47`
- `deer-flow/backend/docs/rfc-create-deerflow-agent.md:1`

规范：

- 顶层允许保留自定义 StateGraph / workflow
- 但所有复杂 agent 行为节点应尽量运行在 DeerFlow agent runtime 上

允许：

- graph 控制阶段流转

不允许：

- graph 节点内部大量使用裸 `model.invoke()` 模拟 agent loop

### 2. DeerFlow 文件管理能力

参考：

- `deer-flow/backend/docs/ARCHITECTURE.md:133`
- `deer-flow/backend/CLAUDE.md:121`
- `deer-flow/README.md:180`
- `deer-flow/backend/docs/CONFIGURATION.md:190`

规范：

- 所有工作流产物必须统一落在 DeerFlow thread workspace 语义下
- 使用 DeerFlow 的 `workspace / uploads / outputs / artifacts`
- 所有代理共享同一 thread-scoped 项目目录
- 推荐部署形态是 Docker / sandbox 模式
- 因此证明工程必须被视为 DeerFlow thread-scoped 的持久化挂载内容，而不是容器临时层里的临时文件

#### 挂载原则

迁移目标不是重新发明一套容器挂载方案，而是：

- **把整个证明项目作为 DeerFlow workspace 内的持久化项目目录运行**

也就是说：

- `/mnt/user-data/uploads` 放原始上传材料
- `/mnt/user-data/workspace` 放运行中的证明工程
- `/mnt/user-data/outputs` 放最终导出物

这条约束直接服务于：

- Docker 部署一致性
- 子代理共享访问
- artifact 暴露
- thread cleanup
- runtime history 与 proof journal 的统一定位

#### 推荐目录结构

```text
thread workspace/project/
├─ references/
│  ├─ raw/
│  ├─ ocr/
│  └─ structured/
├─ informal/
│  ├─ proofs/
│  ├─ verification/
│  ├─ plans/
│  └─ failures/
├─ formal/
│  └─ Lean project root
├─ memory/
│  ├─ rethlas/
│  └─ archon/
├─ journal/
├─ manifests/
└─ scratch/
```

要求：

- 不再把自定义隐藏目录当作平行工作区
- 领域日志可以存在，但必须位于 DeerFlow workspace 中
- `workspace/project/` 是 Archon / Rethlas 的主工作目录
- `outputs/` 只用于最终导出物，不承担主要中间状态存储
- `uploads/` 只用于原始输入，不直接承担项目工作区职责

### 3. `get_available_tools()` 工具聚合

参考：

- `deer-flow/backend/docs/ARCHITECTURE.md:180`
- `deer-flow/backend/CLAUDE.md:96`

规范：

- 所有 agent/subagent 的工具暴露面由 DeerFlow 工具聚合层决定
- Lean LSP、web search、file tools、bash、MCP 都走统一工具入口
- 用 tool groups 控制不同 agent 的权限边界

不应再做：

- 每个节点私自拼接一套局部工具集合

### 4. MCP 设施

参考：

- `deer-flow/backend/docs/MCP_SERVER.md:1`

规范：

- Lean LSP / theorem search 等协议化工具应优先走 MCP
- extensions 配置统一放入 DeerFlow MCP 配置系统
- 不额外创造一层平行 MCP 管理逻辑

### 5. Sandbox 生命周期

参考：

- `deer-flow/backend/docs/ARCHITECTURE.md:133`
- `deer-flow/backend/docs/CONFIGURATION.md:190`

规范：

- 命令执行、文件读写、路径映射统一走 DeerFlow sandbox provider
- 主路径不再依赖宿主机直接 I/O
- 若为本地 provider，也必须保持 DeerFlow 虚拟路径语义一致

### 6. Checkpointer

参考：

- `deer-flow/backend/docs/rfc-create-deerflow-agent.md:121`

规范：

- unified workflow 与 archon workflow 必须挂 checkpointer
- 所有长时 formalization 必须可恢复、可续跑、可分叉

### 7. Middleware Chain

参考：

- `deer-flow/backend/CLAUDE.md:121`

以下 DeerFlow 横切能力必须尽量复用：

- ToolErrorHandlingMiddleware
- LoopDetectionMiddleware
- ClarificationMiddleware
- TokenUsageMiddleware
- ThreadDataMiddleware
- UploadsMiddleware
- SummarizationMiddleware（长上下文阶段）
- MemoryMiddleware（长期用户记忆，不替代 problem memory）

要求：

- 不用 graph 节点手工复刻这些能力

### 8. Run Event / History

参考：

- `deer-flow/backend/CLAUDE.md:244`
- `deer-flow/docs/superpowers/specs/2026-04-11-runjournal-history-evaluation.md:1`

规范：

- DeerFlow event/history 是 runtime 记录层
- proof journal 是领域报告层
- 两者必须共存

要求：

- 关键动作进入 DeerFlow runtime 事件流
- 领域总结保留在项目 workspace 中

---

## 五、Rethlas 的 DeerFlow-native 迁移规范

### 目标

在不降低论文能力的前提下，将 Rethlas 重建为 DeerFlow runtime 上的非形式化研究代理系统。

### 1. 结构要求

必须保留：

- generation agent
- verification agent
- 10 个 skill 的 adaptive selection
- proof repair loop
- problem memory
- theorem retrieval

### 2. DeerFlow 实现要求

#### Generation Agent

应实现为：

- DeerFlow agent runtime
- 绑定 Rethlas skill tools
- 使用 DeerFlow tool aggregation 提供检索、文件、搜索、MCP 工具

不应实现为：

- 大 prompt + 裸 `model.invoke()`

#### Verification Agent

应实现为：

- 独立 DeerFlow agent 或独立 verification stage
- 有独立上下文与输出规范

不应与 generation 混成单轮内部自检。

#### Recursive Proving

必须升级为：

- DeerFlow subagent runtime
- 或 DeerFlow agent 实例并行运行

禁止：

- `ThreadPoolExecutor + model.invoke()`

#### Problem Memory

Rethlas memory 继续保留 problem-specific 设计。

推荐：

- 仍使用 channelized artifact 结构
- 文件落 DeerFlow workspace
- 执行轨迹同步进入 DeerFlow runtime history

### 3. Rethlas 阶段的工具规范

最少需要：

- theorem retrieval（Matlas / 替代）
- web search
- memory read/write
- file read/write
- optional subagent spawning

### 4. Rethlas 的参考基线

行为与结构参考：

- `Rethlas/agents/generation/AGENTS.md:1`
- `Rethlas/agents/verification/AGENTS.md:1`
- `source_paper.md:82`

---

## 六、Archon 的 DeerFlow-native 迁移规范

### 目标

在保留双代理结构、三阶段流程、跨 session review 的前提下，将 Archon 重建为 DeerFlow runtime 上的形式化工作流系统。

### 1. Scaffolding 阶段

参考：

- `source_paper.md:335`
- `Archon/.archon-src/prompts/prover-autoformalize.md:1`

必须保留：

- informal proof / references ingestion
- project initialization
- theorem signatures / definitions / file decomposition
- 初始 `sorry` skeleton 生成

不能简化为：

- “如果没有 Lean 文件就生成 Main.lean”

### 2. Plan Agent

参考：

- `source_paper.md:367`
- `Archon/.archon-src/prompts/plan.md:1`

职责：

- 总结当前状态
- 读取 review / memory / current blockers
- 生成 targeted proving hints
- 做 decomposition / reroute / persistence guidance

实现建议：

- DeerFlow agent runtime
- 短上下文、清洁上下文
- 读 workspace 中的 journal + memory + references

### 3. Lean Agent

参考：

- `source_paper.md:335`
- `Archon/.archon-src/prompts/prover-prover.md:1`

职责：

- 对局部文件 / obligation 进行 formalization
- 调用 LeanSearch / LSP / file tools / informal agent / web/reference
- 尝试 proof completion 和修复

实现建议：

- DeerFlow subagent
- 受限工具集
- sandbox-first
- loop detection + tool error handling

### 4. 多 Lean Agent 并行

参考：

- `source_paper.md:335`

当 proof obligations 可拆分时：

- 使用 DeerFlow subagent execution 做并行任务
- 并行单元为：
  - 文件
  - lemma cluster
  - decomposition branch

### 5. Review Agent

参考：

- `source_paper.md:377`
- `Archon/.archon-src/prompts/review.md:1`

职责：

- 读取最近 session 结果
- 总结跨 session 趋势
- 标记 stall / dead end / promising route
- 为下一轮 Plan Agent 提供策略输入

Review Agent 不是可选的报告装饰层，而是论文级核心能力。

### 6. Polish 阶段

参考：

- `source_paper.md:335`
- `Archon/.archon-src/prompts/prover-polish.md:1`

必须保留：

- compile pass
- zero `sorry`
- zero `axiom`
- warning / redundancy / extractable lemma review
- 最终 artifact 输出

---

## 七、推荐总架构

```text
DeerFlow Gateway Runtime
  ↓
Unified Proof Workflow
  ├─ Stage 1: Rethlas Search / Generate / Verify / Repair
  │   ├─ Generation Agent (DeerFlow agent)
  │   ├─ Verification Agent (DeerFlow agent)
  │   ├─ Recursive Proving Subagents
  │   └─ Problem Memory
  ├─ Stage 2: Archon Scaffolding
  │   ├─ Reference organization
  │   ├─ Lean project initialization
  │   └─ Formal skeleton generation
  ├─ Stage 3: Archon Proving Loop
  │   ├─ Plan Agent
  │   ├─ Parallel Lean Agents
  │   ├─ Reviewer
  │   └─ Review Agent
  └─ Stage 4: Verification / Polish / Export
```

其中：

- DeerFlow 负责 runtime
- 论文结构负责 domain logic

---

## 八、文件管理规范

### 0. Docker 部署与挂载语义

DeerFlow 本身推荐 Docker / sandbox 驱动部署。

因此本项目最终的运行形态应当是：

> **Archon + Rethlas 证明工程挂载在 DeerFlow thread workspace 上运行**

而不是：

> 在容器里临时散落生成项目文件，再由外部脚本补救持久化

必须坚持以下语义分工：

- `/mnt/user-data/uploads`
  - 用户上传文件
  - 原始 PDF / problem statement / reference docs
- `/mnt/user-data/workspace`
  - 运行中项目
  - proof search artifacts
  - Lean 项目
  - memory
  - journal
- `/mnt/user-data/outputs`
  - 最终导出物
  - 可下载报告
  - 打包后的交付内容

如果未来采用 DeerFlow Docker 部署，这套语义必须保持不变。

### 1. 统一 DeerFlow workspace

所有项目文件必须归入 DeerFlow thread workspace。

### 2. 参考资料管理

参考：

- `source_paper.md:353`
- `source_paper.md:377`

要求：

- paper/pdf/ocr/structured markdown 分目录管理
- 原始 references 与 agent 生成的 proof-route notes 分离

推荐：

```text
references/
├─ original_papers/
├─ extracted_text/
├─ structured_notes/
└─ agent_added/
```

### 3. informal 与 formal 分离

要求：

- informal candidate proofs、verification reports、plans、failures 与 Lean 项目分离
- 避免上下文污染和文件混杂

### 4. journal 与 runtime history 分离

要求：

- runtime history 由 DeerFlow 维护
- proof journal 由 workflow 维护
- 二者路径或 ID 可互相映射

---

## 九、memory 规范

### 1. 双层 memory

必须显式区分：

- **DeerFlow memory**
  - 用户偏好
  - 长期交互上下文
  - 通用会话记忆

- **Problem memory**
  - decomposition plans
  - failed paths
  - candidate proof routes
  - file-specific blockers
  - cross-session review conclusions

不能用 DeerFlow memory 替代论文中的 problem memory。

### 2. review 驱动 memory

review agent 的输出必须反馈进：

- next planner cycle
- next proving cycle
- branch pruning
- session-level rerouting

---

## 十、反模式

### 1. 用 DeerFlow 单一 lead agent 替代论文结构

不允许。

### 2. 在关键节点使用裸 `model.invoke()`

若行为本质是：

- 工具选择
- 多轮迭代
- 错误恢复
- 分支探索

则必须优先 DeerFlow agent/subagent runtime。

### 3. 用 DeerFlow memory 粗暴替代 Rethlas/Archon problem memory

不允许。

### 4. 用 graph 节点重复实现 middleware

例如：

- loop detection
- tool error handling
- clarification
- token accounting

应避免。

### 5. 继续维护平行文件系统

隐藏状态目录可以有，但不应脱离 DeerFlow workspace 语义。

### 6. 把 Review Agent 降级成“生成 Markdown 总结”

不允许。

它必须参与策略调度。

---

## 十一、分阶段实施规范

### Phase 1：修复当前状态闭环

先修当前实现中的基础问题：

- attempts 真实写入
- completed 真实维护
- review 对下一轮可见
- artifacts 与实际文件一致

### Phase 2：Rethlas DeerFlow-native 化

顺序建议：

1. generation agent DeerFlow 化
2. verification agent DeerFlow 化
3. recursive_proving DeerFlow subagent 化
4. problem memory 与 DeerFlow workspace/event 对齐

### Phase 3：Archon DeerFlow-native 化

顺序建议：

1. scaffolding 阶段做实
2. Plan Agent DeerFlow 化
3. Lean Agent subagent 化
4. Review Agent 做成真正的 session strategist

### Phase 4：Runtime 统一

1. checkpointer 统一
2. run events 统一
3. file/workspace 统一
4. tool exposure 统一
5. middleware 能力统一

---

## 十二、验收标准

当以下条件满足时，可认为迁移达到目标。

### A. 结构保持

- Rethlas 仍是双代理闭环
- Archon 仍是双代理 + 三阶段
- review / memory / reroute 结构保留

### B. DeerFlow 利用充分

- 统一 workspace / outputs / artifacts
- 统一 sandbox lifecycle
- 统一 tool aggregation
- 统一 MCP 配置
- 统一 checkpointer
- 统一 runtime event/history

### C. 行为不退化

- recursive exploration 保留
- plan-guided proving 保留
- cross-session review 保留
- autonomous gap-filling 目标不变

### D. 维护性提升

- 平行运行时减少
- 平行工具层减少
- 平行文件系统减少
- workflow 与 runtime 边界清晰

---

## 十三、最终定位

该迁移项目的最终定位应为：

> **A paper-aligned Archon + Rethlas reimplementation on top of DeerFlow runtime**

而不是：

> **A DeerFlow-flavored approximation of Archon and Rethlas**

前者要求：

- 保留论文系统结构
- 参考原始实现细节
- 最大化利用 DeerFlow runtime 和文件/编排能力

这是本项目应遵循的最高级规范。
