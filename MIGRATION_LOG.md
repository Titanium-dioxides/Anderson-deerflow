# MIGRATION_LOG.md — Archon + Rethlas → DeerFlow 移植记录

> 📋 **本项目开发准则：**
> 1. **每次代码修改必须记录在 `MIGRATION_LOG.md`** — 格式: `YYYY-MM-DD: [组件] 改动说明`
> 2. **每次修改代码后必须执行冒烟测试** — 规则见 `SMOKE_TEST.md`
> 3. **测试结果记录在 `SMOKE_TEST_LOG.md`** — 通过则删除测试代码，失败则保留并标记
> 4. **每次修改后必须 `git commit`** — commit message 须包含改动摘要
> 5. **维护 `TODO.md`** — 未完成功能、已知问题、待改进项，按优先级排列。每次发现新问题必须更新
> 6. **维护 `BLOCKERS.md`** — 区分受阻问题（外部依赖/架构限制）与未实现功能。每次解除 blocker 必须记录

---

## 2026-05-14

### [docs-deerflow] 学习 DeerFlow 官方文档后重新评估 BLOCKERS.md
- **文件:** `BLOCKERS.md` (更新)
- **学习来源:** `README_zh.md`, `ARCHITECTURE.md`, `MCP_SERVER.md`, `tools/tools.py`, `mcp/tools.py`, `agents/lead_agent/agent.py`, `subagents/`
- **关键发现:**
  - `get_available_tools()` 已集成 MCP（通过 `get_cached_mcp_tools()`），可直接 `model.bind_tools()`
  - `deerflow.subagents` 原生支持并行子 agent
  - lead_agent 使用 `create_agent()` 模式，非直接 `model.invoke()`
- **BLOCKERS.md 状态变更:**
  - B1: 🚧外部依赖 → ⚡架构可解决（调用 `get_available_tools()` 即可）
  - B2: 🚧外部依赖 → ⚡自动解除（B1 解决后 LLM 可自选 exact/apply）
  - B4:  约束 → ⚡架构可解决（`deerflow.subagents` 可用）

### [blockers] 新增 BLOCKERS.md + COMPARISON.md — 差距分析与受阻原因
- **文件:** `BLOCKERS.md` (新建), `COMPARISON.md` (新建)
- **内容:**
  - COMPARISON.md：6 维度 30+ 项能力对照表，综合移植度 68%
  - BLOCKERS.md：3 个受阻问题 + 1 个架构约束 + 2 个未实现功能，含依赖树
- **准则:** MIGRATION_LOG.md 增加第 6 条开发准则——维护 BLOCKERS.md

### [todo] 新增 TODO.md — 待解决问题跟踪文件
- **文件:** `TODO.md` (新建)
- **内容:** 10 项待解决问题，按高/中/低优先级排列，包含已知障碍和可能的方案
- **准则:** MIGRATION_LOG.md 增加第 5 条开发准则——维护 TODO.md

### [phase3] 自动化策略级联 — rfl→simp→ring→linarith→omega→aesop→grind
- **文件:** `overlay/backend/workflows/archon_graph.py`, `overlay/backend/workflows/unified_graph.py`
- **改动:**
  - 新增 `_AUTO_TACTICS = ["rfl", "simp", "ring", "linarith", "omega", "aesop", "grind"]`
  - 新增 `_try_tactics_cascade(ws, f, content)` — 对单个 sorry 尝试策略级联，每次从原始内容替换，通过 `_verify_file` 增量验证
  - 新增 `_try_tactics_cascade_all(ws, f)` — 循环调用 cascade 直到全部 sorry 解决或某一 sorry 无解
  - prover 在调 LLM 前先执行级联：全解决→跳过 LLM，部分解决→LLM 接手剩余
- **原版对应:** 恢复原 Archon 的 auto-tactics cascade (rfl→simp→ring→linarith→omega→exact?→apply?→grind→aesop)
- **测试:** 26/26 冒烟测试通过

### [dev-standards] 新增冒烟测试规范 + SMOKE_TEST.md + SMOKE_TEST_LOG.md
- **文件:** `SMOKE_TEST.md` (新建), `SMOKE_TEST_LOG.md` (新建)
- **改动:** 确立 4 条项目开发准则，要求每次修改代码后执行冒烟测试、记录结果、git commit
- **测试:** L0+L1+L2 冒烟测试 42/42 通过
- **配套:** `tests/fixtures/sample.lean` 测试样本文件

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

### [Phase 1: 增量编译 + 结构化错误解析](#)
- **文件:** `overlay/backend/workflows/archon_graph.py`, `overlay/backend/workflows/unified_graph.py`
- **原状:** prover 每次修改 .lean 文件后都跑 `lake build`（全量项目编译，5-30s），错误信息以原始字符串截断传送
- **改动:**
  - **新增 `_verify_file(ws, f)`** — 用 `lake env lean <file>` 进行单文件增量验证（~1-2s），替代 `_build(ws)` 全量编译
  - **新增 `_parse_lean_errors(stderr)`** — 将 Lean 编译器 stderr 解析为结构化记录：`{type, severity, file, line, col, message, raw}`
  - **新增 `_classify_error(msg)`** — 将错误消息分类为 10 种类型：`type_mismatch`, `unknown_identifier`, `failed_to_synthesize`, `don_know_how`, `invalid`, `syntax_error`, `ambiguous`, `type_error`, `unsolved_goal`, `other`
  - **新增 `_format_errors(errors)`** — 将结构化错误格式化为 LLM-readable 文本（最多 5 个错误 × 8 行消息）
  - **prover/prover_node 重写：**
    - `_build(ws) → _verify_file(ws, f)` 在主尝试和 fallback 尝试中
    - 错误信息从截断原始字符串 `log[-2000:]` 改为结构化格式化 `_format_errors(verrors)`
    - reasoner prompt 接收结构化错误（标注类型和位置），而非原始日志
    - fallback attempt 同样携带结构化错误
  - **reviewer/reviewer_node 保留 `_build(ws)`** 用于最终全量编译验证（只有此处用全量）
- **原版对应:** 恢复原 Archon 三级验证阶梯中的第一级（per-file `lake env lean`）和第二级（结构化错误 → LLM 引导修复）
- **效果:** 单文件验证从 5-30s 降至 ~1-2s，错误信息从原始字符串变为结构化格式

### [Phase 2: 目标提取 + Mathlib 搜索](#)
- **文件:** `overlay/backend/workflows/archon_graph.py`, `overlay/backend/workflows/unified_graph.py`
- **原状:** prover 接收整个 .lean 文件做证明，planner 只传 sorry 上下文给 LLM，无精确目标信息
- **改动:**
  - **新增 `_extract_goal(ws, f, line_str)`** — 解析 .lean 文件，从 sorry 位置向上扫描找到 enclosing theorem/lemma/def/example/instance/corollary 声明，提取其签名（最多 30 行）。使用 `re.compile(r'^\s*(theorem|lemma|def|example|instance|corollary|class|structure|abbrev)\b')` 匹配声明起始
  - **planner 增强：** 对每个 sorry 提取精确目标签名 → 注入到 planner prompt 中（`## 每个 sorry 的精确定理签名`），并在 planner 中调用 `_search_mathlib()` 搜索相关定理 → 注入到 prompt（`## Mathlib 相关定理`）
  - **prover 增强：** SystemMessage 和 reasoner prompt 都添加 `goal_ctx` 块，包含填充目标的定理签名
  - **`_search_mathlib(query)`** — 新增到 archon_graph.py，调用 leansearch.net API 搜索相关定理
  - **`unified_graph.py` 修复 `_search()`** — resp.read() 调用顺序修复（先 read 再 decode）
- **原版对应:** 恢复原 Archon 的 `lean_goal(file, line)` 获取精确目标的能力（通过文件扫描模拟），以及 `lean_leansearch()` / `lean_local_search()` 的搜索能力（通过 leansearch.net API 模拟）
- **效果:** LLM 不再猜测目标类型，每次证明请求都包含精确定理签名；planner 可获得 mathlib 中已知相关定理作为参考

### [_local_lean_search — 实现本地声明搜索](#)
- **文件:** `overlay/backend/workflows/archon_graph.py`, `overlay/backend/workflows/unified_graph.py`
- **原状:** 只实现了 `_search_mathlib()` 远程 leansearch.net API，无本地搜索
- **改动:**
  - **新增 `_local_lean_search(query, ws, max_results)`** — 搜索 Lean 声明匹配查询字符串
  - **搜索范围：** （1）项目 .lean 文件（排除 .lake）→ （2）mathlib 主要子目录（Algebra/Analysis/Data/Logic/SetTheory/Topology/NumberTheory） → （3）Lean stdlib（通过 `lean --print-prefix` 定位）
  - **排序：** 精确匹配 > 前缀匹配 > 包含匹配；项目文件 > mathlib 依赖（与原版 `_local_search_sort_key` 逻辑一致）
  - **原版对应：** 恢复原 Archon `lean_local_search()` 的核心语义
  - **集成：** planner 同时做远程搜索 + 本地搜索，结果合并注入提示词
- **性能说明：** 原版使用 ripgrep（rg）高速搜索，移植版用 `grep -rnHP` 降级。rg 安装后可自动提速
