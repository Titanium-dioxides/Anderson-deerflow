# MIGRATION_LOG.md — Archon + Rethlas → DeerFlow 移植记录

> 每次修改必须在此记录。格式: `YYYY-MM-DD: [组件] 改动说明`

---

## 2026-05-14

### [deerflow] generator.md — 重写为独立数学推理提示词
- **文件:** `overlay/skills/custom/math-prover/prompts/generator.md`
- **原状:** 直接拷贝自 Rethlas `agents/generation/AGENTS.md` (Codex 代理编排器)，引用 `search_arxiv_theorems`、`$construct-counterexamples` 等 deerflow 环境不存在的工具和技能
- **改动:** 重写为 standalone LLM 提示词，保留原 Rethlas 的 10 种自适应推理策略（搜索、反例构造、子目标分解、递归证明等）作为思维框架，移除所有对外部 MCP/Codex 工具的引用
- **效果:** 提示词可直接作为 deerflow `SystemMessage` 使用，模型仍按原 Rethlas 的数学推理方法论输出

### [deerflow] verifier.md — 重写为独立证明验证提示词
- **文件:** `overlay/skills/custom/math-prover/prompts/verifier.md`
- **原状:** 直接拷贝自 Rethlas `agents/verification/AGENTS.md`，引用 `$verify-sequential-statements` 等子技能和 `search_arxiv_theorems` MCP
- **改动:** 重写为 standalone LLM 提示词，保留原验证代理的三大验证步骤（顺序语句检查 → 外部引用验证 → 综合报告）、strict verdict 规则和 JSON schema
- **效果:** 验证器输出符合原 `verification_output.schema.json` 格式，无外部依赖

### [deerflow] unified_graph.py — 修复提示词路径为项目本地路径
- **文件:** `overlay/backend/workflows/unified_graph.py`
- **原状:** `_RETHLAS_DIR` 硬编码指向 `/home/zdzdhd/deer-flow/skills/custom/math-prover`（外部 deer-flow 实例路径）
- **改动:** 改为项目内相对路径 `overlay/skills/custom/math-prover`
- **效果:** 不再依赖外部 deer-flow 实例，容器内和独立开发环境均可运行

### [archon_graph.py — 增强版 Plan Agent](#)
- **文件:** `overlay/backend/workflows/archon_graph.py`
- **原状:** planner 节点仅 `grep sorry → 让模型排序`，prover 节点无失败模式感知，reviewer 节点只有简单的 build PASS/FAIL 判断
- **改动:**
  - **ArchonState** 新增 `attempt_history`, `failure_modes`, `informal_hints`, `previous_strategies`, `user_hints` 五个字段
  - **planner()** 重写：扫描 sorries → 读取 attempt_history → 用关键字匹配识别 5 种失败模式（missing_infrastructure / typeclass / wrong_construction / early_stopping / compilation_error）→ 生成非形式化证明指引 + 建议策略 → 设置子目标 → 注入已有的 Rethlas 指引
  - **prover()** 增强：使用 planner 生成的指引作为 SystemMessage 上下文 → 根据失败模式调整证明策略（如缺失基础设施则建议 induction/recursion 基础方法）→ 每次尝试记录到 attempt_history（含 strategy, result, lean_error, failure_mode）→ 推理模型 fallback 同样接收失败信息
  - **reviewer()** 增强：汇总 attempt_history 生成失败模式分布统计 → 审查摘要包含已完成数、待处理数、总尝试次数、失败模式分布
- **原版对应:** 恢复原 Archon Plan Agent 的 4 项能力：失败模式识别、非形式化指引生成、attempt 历史跟踪、目标设定
- **效果:** planner 现在是有上下文感知的（知道之前为什么失败），prover 能从失败模式中获取策略调整

### [unified_graph.py — 同步增强 Archon 节点](#)
- **文件:** `overlay/backend/workflows/unified_graph.py`
- **改动:**
  - **UnifiedState** 新增 `attempt_history`, `failure_modes`, `informal_hints`, `previous_strategies` 四个字段
  - **planner_node()** 重写：同步 archon_graph.py 的增强逻辑
  - **prover_node()** 增强：使用 planner_node 的指引 + 失败模式感知 + attempt 记录
  - **reviewer_node()** 增强：失败模式分布统计
  - 新增 `_classify_failure()` 工具函数，与 archon_graph.py 共享相同的分类逻辑
- **效果:** unified_prover 工作流的 Archon 端与独立 archon_workflow 能力一致

### [archon_graph.py — 新增 Review Agent 节点](#)
- **文件:** `overlay/backend/workflows/archon_graph.py`
- **原状:** 无审查代理，reviewer 只输出 build PASS/FAIL，无跨迭代知识保留
- **改动:**
  - 新增 `review_agent` 节点，位于 `reviewer → (review_agent) → planner` 路径
  - 分析 `attempt_history` → 按文件分组 → 为每文件生成结构化里程碑（含 attempt 详情、策略、错误、insight）
  - 写入 4 个 journal 文件到 `{ws}/.archon-journal/`:
    - `session_{N}/summary.md` — 本轮详细摘要（每文件状态、尝试次数、失败模式）
    - `session_{N}/milestones.jsonl` — 每文件 JSONL 里程碑格式（匹配原 Archon spec）
    - `session_{N}/recommendations.md` — 下轮行动建议（阻塞/进行中分类）
    - `PROJECT_STATUS.md` — 累积状态（总 sorry、已知阻塞列表）
  - 路由改为 `reviewer → review_agent → planner` 或 `→ END`
- **原版对应:** 恢复原 Archon Review Agent 的 3 项核心能力：per-attempt 分析、milestones.jsonl 输出、recommendations 生成
- **效果:** 跨迭代的知识保留机制就位——planner 每次循环前可读取之前的分析

### [unified_graph.py — 同步 Review Agent 节点](#)
- **文件:** `overlay/backend/workflows/unified_graph.py`
- **改动:**
  - 新增 `review_agent_node` 节点，同步 archon_graph 的审查逻辑
  - `route_archon` 改为 `reviewer → review_agent_node → planner` 或 `→ generator`(失败反馈) 或 `→ END`
  - 图结构加入 `review_agent_node` 节点，`add_edge("review_agent_node", "planner")`
- **效果:** unified_prover 工作流也具备跨迭代的审查期刊能力
