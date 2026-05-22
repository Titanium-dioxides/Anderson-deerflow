# DEVELOPMENT_ROADMAP.md

## 目标

本文件将当前迁移规划整理为可执行开发路线，服务于：

- 保留 `source_paper.md` 的论文级能力
- 对齐原始 `Rethlas` 与 `Archon` 的 agent 编排逻辑
- 最大化复用 DeerFlow 的编排、文件管理、sandbox、tools、subagents、checkpointer、runtime history

主规范见：

- `DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md`
- `DEERFLOW_REFERENCE.md`

---

## 总体目标架构

```text
DeerFlow Gateway / Runtime
  ↓
Unified Proof Workflow
  ├─ Rethlas Stage
  │   ├─ Generation Agent
  │   ├─ Verification Agent
  │   ├─ Skills / Retrieval / Memory
  │   └─ Recursive Proving Subagents
  ├─ Archon Scaffolding Stage
  │   ├─ Reference ingestion
  │   ├─ Lean project initialization
  │   └─ Formal skeleton generation
  ├─ Archon Proving Stage
  │   ├─ Plan Agent
  │   ├─ Lean Agent(s)
  │   ├─ Reviewer
  │   └─ Review Agent
  └─ Polish / Export Stage
```

---

## 阶段规划

### Phase 0 — 规范冻结

**目标**

- 冻结迁移边界、目录结构、工具边界、输入输出契约

**产出**

- `DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md`
- 本文档
- `SMOKE_TEST.md`

**完成标准**

- 统一接受“保留算法结构，替换运行时基础设施”原则
- 明确 `uploads / workspace / outputs` 语义

---

### Phase 1 — DeerFlow Runtime 骨架

**目标**

- 先搭 DeerFlow 原生运行底座

**工作项**

1. 注册统一 workflow 入口
2. 挂接 checkpointer
3. 确定 thread workspace 目录结构
4. 对齐 MCP / sandbox / tool aggregation 主路径
5. 定义 artifacts 暴露方式

**阶段测试目标**

- 能启动一个空 workflow
- 能在 DeerFlow workspace 下创建项目目录
- 能通过 sandbox 读写文件
- 能暴露一个测试 artifact
- 能在同一 thread 上恢复一次 run

---

### Phase 2 — Rethlas DeerFlow-native 化

**目标**

- 重建论文要求的非形式化证明闭环

**工作项**

1. 实现 generation agent（DeerFlow agent）
2. 实现 verification agent（DeerFlow agent / structured stage）
3. 迁移 10 个 skill tools
4. 建立 problem-specific memory
5. 将 recursive proving 改为 DeerFlow subagent runtime
6. 打通 theorem retrieval / web search / file tools

**阶段测试目标**

- 对简单问题，生成→验证→修复能完成闭环
- skills 能被自主调用，不依赖硬编码固定顺序
- recursive proving 至少能并行执行 2 个 plan
- problem memory 能记录 plans / failures / examples / proof drafts

---

### Phase 3 — Archon Scaffolding

**目标**

- 从 informal proof / references 自动生成 Lean 项目骨架

**工作项**

1. references 归档与结构化
2. formal project initialization
3. theorem / definition skeleton 生成
4. 文件切分
5. manifests / journal 基础结构生成

**阶段测试目标**

- 输入 informal proof 后能自动生成 Lean 项目目录
- 至少能拆出主定理与辅助引理
- `lake build` 可运行到“仅剩 `sorry`”状态
- references / formal / memory / journal 目录结构稳定

---

### Phase 4 — Archon Proving Loop

**目标**

- 重建论文要求的 Plan Agent + Lean Agent + Review Agent 工作流

**工作项**

1. Plan Agent DeerFlow 化
2. Lean Agent subagent 化
3. 并行 proving
4. Reviewer 纯逻辑节点
5. Review Agent 做成跨 session strategist
6. attempt / failure / completed 状态闭环

**阶段测试目标**

- `attempt_history`、`completed`、`failure_modes` 有真实写入
- 单文件与多文件 proving 都能收敛
- Plan Agent 能根据上一轮失败改变策略
- Review Agent 能阻止重复走死路

---

### Phase 5 — Polish / Export / Runtime History

**目标**

- 补齐最终交付与 DeerFlow 运行记录

**工作项**

1. final checks
2. `sorry` / `axiom` 检查
3. artifact 打包
4. outputs 导出
5. run events / history 映射
6. proof journal 与 DeerFlow history 对齐

**阶段测试目标**

- 最终项目满足 `0 sorry`、`0 axiom`
- 能输出报告和 Lean 项目交付物
- DeerFlow history 可追踪关键阶段与子代理

---

### Phase 6 — 端到端验收

**目标**

- 验证能力不降级

**工作项**

1. 构造简单题基准
2. 构造检索驱动题基准
3. 构造多轮 formalization 题基准
4. 与现实现状对比

**阶段测试目标**

- 简单题：全流程稳定通过
- 检索题：能找到外部定理并进入 formalization
- 困难题：体现 decomposition / reroute / review / multi-session 行为

---

## 当前优先顺序

1. Phase 1
2. Phase 2
3. Phase 3
4. Phase 4
5. Phase 5
6. Phase 6

其中真正的能力门槛在：

- Phase 2：Rethlas 闭环
- Phase 4：Archon proving loop

---

## 关键门槛

### Gate A

Rethlas 可独立完成：

- generation
- verification
- repair
- recursive exploration

### Gate B

Archon 可独立完成：

- scaffolding
- Lean skeleton generation
- references organization

### Gate C

Archon proving loop 可完成：

- plan-guided proving
- parallel Lean agents
- review-driven reroute

### Gate D

端到端 workflow 可完成：

- informal → formal
- compile / polish
- artifact export

