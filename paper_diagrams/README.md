# Paper 架构图学习笔记

> 下载时间：2026-05-19
> 来源：https://frenzymath.com/ 6 个 SVG 图

---

## 1. whole_pipeline.svg — 框架整体流水线

```
┌──────────────────────────────────────────────────────────────────┐
│                          Rethlas (Informal Agent)                │
│                                                                    │
│  ┌──────────────────┐     ┌──────────────────┐                   │
│  │  Generation Agent │────▶│ Verification Agent│                  │
│  │  (Propose Proofs) │◀────│ (Verify Proofs)  │ (≤3 rounds)      │
│  └──────────────────┘     └──────────────────┘                   │
│         │                       │                                  │
│         ▼                       ▼                                  │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Tools:  Matlas(Theorem Retrieval) ─── Web Search          │   │
│  │          Memory Manage(Reading & Logging)                   │   │
│  └────────────────────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Skills: Construct examples — Construct counterexamples    │   │
│  │          Propose subgoal decomposition plans                │   │
│  │          Identify key failures                              │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│                      Candidate Informal Proof                     │
└──────────────────────────────────┬────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                          Archon (Formal Agent)                   │
│                                                                    │
│  1. (Re)Write Formal Sketch — split files & theorems              │
│     → compile & semantics check (pass/fail)                       │
│                                                                    │
│  2. Formalize — generate & fix proof                              │
│     → 0 sorry & compiles (pass/fail)                              │
│                                                                    │
│     Strategies (when stuck):                                      │
│     ① Ask Informal Agent (Detailing) — more detailed proof steps │
│     ② Decompose — split into smaller sub-lemmas                   │
│     ③ Ask Informal Agent (Re-routing) — alternative proof route  │
│                                                                    │
│  3. Final Checks → Polish & Done                                  │
│     (warnings · redundancy · specificity)                         │
└──────────────────────────────────────────────────────────────────┘
```

**关键 insight：** Paper 中 Archon 的"Ask Informal Agent"回路在统一的子系统中运行（非形式化证明的反向调用属于同一系统）。我们 `unified_graph.py` 实现了这个回路（`archon_feedback → generator`），但 Rethlas 侧的能力（10 个自适应技能 + Matlas）差距较大。

---

## 2. rethlas_agent.svg — Rethlas Agent 架构

```
                  ┌──────────────────────┐
                  │    Generation Agent   │ ◀─── Skills
                  │  (Propose Proofs)     │       ├── Construct examples
                  └──────────┬───────────┘       ├── Construct counterexamples
                             │                    ├── Propose subgoal 
                  ┌──────────▼───────────┐        │    decomposition plans
                  │   Verification Agent │        └── Identify key failures
                  │  (Verify Proofs)     │
                  └──────────┬───────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
  ┌────────────┐    ┌──────────────┐    ┌──────────────────┐
  │   Matlas   │    │  Web Search  │    │  Memory Manager  │
  │  Theorem   │    │   Reference  │    │  Reading &       │
  │ Retrieval  │    │    Lookup    │    │  Logging         │
  └────────────┘    └──────────────┘    └──────────────────┘
```

**关键 insight：** Rethlas 的核心是 **Generation + Verification 双 Agent**，它们**共享同一套 Tools 和 Skills**。Tools 提供外部信息（数学检索、网络搜索、记忆），Skills 提供内部方法（构造例子/反例、分解方案、识别关键失败）。

我们在 `unified_graph.py` 中也有 generation + verification 两个节点，但 Skills 被压缩为单 prompt，Memory Manager 未实现。

---

## 3. Archon_Workflow.svg — Archon 工作流

```
                   Archon Workflow
                   
                   ┌──────────────────────┐
                   │   Read & Search      │
                   │   Informal Materials │
                   └──────────┬───────────┘
                              │
              ┌───────────────▼───────────────┐
              │  (Re)Write Formal Sketch      │  ← Scaffolding
              │  split files & theorems       │
              └───────────────┬───────────────┘
                              │
                     compile & semantics ──── no ───→ (rewrite)
                              │
                             yes
                              │
              ┌───────────────▼───────────────┐
              │         Formalize             │  ← Proving
              │  generate & fix proof         │
              └───────────────┬───────────────┘
                              │
                    0 sorry & compiles ──── no ───→ Strategies
                              │                     ① Ask Informal
                             yes                    (Detailing)
                              │                     ② Decompose
              ┌───────────────▼───────────────┐     ③ Ask Informal
              │         Final Checks          │     (Re-routing)
              └───────────────┬───────────────┘     └──→ retry
                              │
               ┌──────────────▼──────────────┐
               │  Polish & Done              │  ← Polish
               │  warnings · redundancy      │
               │  specificity                │
               └─────────────────────────────┘
```

**关键 insight：** Archon 工作流是**线性的三阶段**（Scaffolding → Proving → Polish），但在 Proving 阶段有**回环机制**（Strategies ①-③）。每次失败后先尝试细化（①），再尝试分解（②），最后尝试路径重规划（③）。

我们在 `archon_graph.py` 中实现了证明循环，但差异在于：
- 我们的 planner 不做 (Re)Write Formal Sketch（Scaffolding）
- 我们的 Strategies（Ask Informal / Decompose / Re-routing）未独立实现
- Polish 阶段未实现

---

## 4. Agent_system_with_tools.svg — Agent 系统与工具

```
                    Agent System
                         │
              ┌──────────┴──────────┐
              │     Plan Agent      │
              │ Summary, Strategy   │
              │ & Decomposition     │
              └──────────┬──────────┘
                         │ dispatch
                         │ iterate
              ┌──────────▼──────────┐
              │ (Multi) Lean Agent(s)│
              │ (Parallel) Proof     │
              │ Attempts             │
              └──────────┬──────────┘
                         │ call / result
                         ▼
        ┌───────────────────────────────────┐
        │ Tools                             │
        │                                   │
        │ Ask Informal Agent                │
        │ (Natural Language Reasoning)      │
        │                                   │
        │ LeanSearch                        │
        │ (Theorem-Definition Retrieval)    │
        │                                   │
        │ Lean LSP MCP                      │
        │ (Diagnostics & Searching)         │
        │                                   │
        │ Web Search                        │
        │ (Reference Lookup)                │
        │                                   │
        │ Memory Manager                    │
        │ (Reading & Logging)               │
        └───────────────────────────────────┘
```

**关键 insight：** Archon 的关键架构 | Plan Agent | 协调 | (Multi) Lean Agent(s) |。Plan Agent **不写代码**，只做策略和分解。Lean Agent 并行工作，通过 Tools 完成任务。Tools 有 5 个：Ask Informal Agent、LeanSearch、Lean LSP MCP、Web Search、Memory Manager。

我们在 `archon_graph.py` 中有类似结构：
- planner → prover（SubagentExecutor）
- 但缺少 **Plan Agent 主动分解**能力
- 缺少 **Memory Manager** 工具
- 缺少 **Ask Informal Agent** 作为独立工具

---

## 5. rethlas_exploration_trajectory.svg — Rethlas 探索轨迹

```
        Broad Search → Focused Search
                │
                ▼
           Attack Plan
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
Plan A       Plan B      Plan C
Attempt     Attempt     Attempt
    │           │           │
    ├── Failure ┼── Failure ┼── Formulation
    │           │           │
    └───────────┴───────────┘
                │
                ▼
         Proof Completion
                │
                ▼
   Natural Language Verification
          Success / Failure
```

**关键 insight：** Rethlas 的探索是**多路并行的**（Plan A/B/C），失败后不放弃，而是转向另一个 Plan。只有当一个分支走通后才进行 NL Verification。这个"多路并行探索"模式在 Rethlas 中是一个重要特征。

我们 `unified_graph.py` 的 Rethlas 部分不具备此能力。探索是线性的（一次生成 → 验证 → 修复）。

---

## 6. code_structure.svg — 形式化代码结构

（这是一个 Matplotlib 生成的 SVG，包含代码目录的可视化树状结构。内容与 Lean 项目代码结构相关，非工作流图。）

---

## 对 archon-deerflow 的改进方向

### 优先（从 SVGs 中提取的关键差距）

| 差距 | SVG 来源 | 对应改进 |
|:----|:---------|:---------|
| Rethlas 10 自适应 Skills | rethlas_agent | 恢复独立 Skills 模块 |
| Plan Agent 主动分解 | Agent_system_with_tools | planner 节点加 LLM 调用 |
| 多路并行探索 | rethlas_exploration_trajectory | 同时尝试多个 proof plan |
| Ask Informal Agent 工具 | Agent_system_with_tools | 为 Lean Agent 提供 NL 推理工具 |
| Memory Manager | Agent_system_with_tools | 持久化内存 + 跨 session 记忆 |
| Scaffolding 阶段 | Archon_Workflow | autoformalize 阶段 |
| Polish 阶段 | Archon_Workflow | polish 阶段（golf, refactor） |
| 回环策略 ①-③ | whole_pipeline | 细化 → 分解 → 重路由级联 |
| Matlas 级别搜索 | rethlas_agent | arXiv + mathlib 双向搜索 |
