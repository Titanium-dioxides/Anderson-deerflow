# AUDIT.md

## 目的

本文件记录"当前实现"相对于"目标规范"的审计结论。

目标规范基线：

- `source_paper.md`
- `Rethlas/`
- `Archon/`
- `DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md`

---

## 当前审计结论（2026-05-24）

### 总评

- Phase 1-6 已完成代码骨架与结构化测试
- DeerFlow thread workspace、Phase 3/4/5 阶段切分、manifest/journal 基线已建立
- 但论文级能力尚未完全落地，主要剩余在更深层的 skill 自主调用质量与 Lean/MCP 能力深度，不再是主路径缺失
- 现有测试主要证明结构与状态机存在，不足以证明真实论文级 proving 能力

---

## 论文→原实现→新实现 对齐表

### A. Rethlas 非形式化证明系统

| 论文能力 | 原实现 | 新实现 | 状态 |
|----------|--------|--------|:--:|
| Generation Agent | `Rethlas/agents/generation/AGENTS.md` → 10 skill 驱动 | `phase2_rethlas.py:generation_agent_node` → DeerFlow agent + 10 tools | ✅ |
| Verification Agent | `Rethlas/agents/verification/AGENTS.md` → 3 skill 严格验证 | `phase2_rethlas.py:verification_agent_node` → 独立 DeerFlow agent | ✅ |
| Generation→Verification 闭环 | generation → verification → repair loop (≤3) | generation → verification → repair state machine（2026-05-24 修正为真实 loop） | 🔶 |
| 10 自适应 skills | 10 个 SKILL.md + agents 配置 | `rethlas_skill_tools.py` 10 个 langchain tool（搜索/验证/分解/记忆）| ✅ |
| Problem memory（10 channel）| `rethlas_memory/{problem_id}/*.jsonl` | `RETHLAS_MEMORY_CHANNELS` + thread/problem-scoped jsonl 写入 | 🔶 |
| 定理检索 | `search-math-results` SKILL → arXiv + web search | `search_mathematical_results` → Web + Matlas + Mathlib + Loogle + LeanSearch | ✅ |
| 示例/反例构造 | `construct-toy-examples` / `construct-counterexamples` SKILLs | `construct_examples` / `construct_counterexamples` → web search + 建议 | ✅ |
| 分解方案提议 | `propose-subgoal-decomposition-plans` SKILL | `propose_decomposition` → web search + 标准化方案 | ✅ |
| 直接证明 | `direct-proving` SKILL | `direct_proving` → web search + tactics 建议 | ✅ |
| 递归多路径探索 | `recursive-proving` SKILL → ThreadPoolExecutor | `recursive_proving` 返回 subagent task 计划；是否被 generation agent 实际采用仍待端到端验证 | 🔶 |
| 失败模式识别 | `identify-key-failures` SKILL | `identify_key_failures` → 模式检测 + 建议 | ✅ |
| 证明验证 | `verify-proof` SKILL → 严格验证 schema | `verify_proof` → 结构检查 + web 对照 | ✅ |

### B. Archon 形式化系统

| 论文能力 | 原实现 | 新实现 | 状态 |
|----------|--------|--------|:--:|
| Plan Agent | `Archon/.archon-src/prompts/plan.md` → 状态总结+策略 | `phase4_archon_proving.py:plan_agent_node` → DeerFlow agent | ✅ |
| Lean Agent(s) | `Archon/.archon-src/prompts/prover-prover.md` → 局部形式化 | `phase4_archon_proving.py:lean_agents_node` → subagent/task 主导，direct agent 仅回退 | ✅ |
| Plan/Lean 上下文隔离 | 独立 agent session | 独立 thread_id 调用 + 独立 context | ✅ |
| Lean Agent 卡住→Plan 重路由 | plan → lean → review → plan loop | `route_after_review` 条件边 → plan_agent | ✅ |
| Reviewer（纯逻辑节点）| reviewer 检查 attempt/completion | `reviewer_node` → Counter + 状态统计 | ✅ |
| Review Agent（跨 session strategist）| `Archon/.archon-src/prompts/review.md` | `review_agent_node` → LLM 策略生成 + history 反馈 | ✅ |
| attempt/completed/failure 状态闭环 | attempt_history / failure_modes | `attempt_history.jsonl` / `failure_modes` / `completed` list | ✅ |

### C. Archon 三阶段流程

| 阶段 | 原实现 | 新实现 | 状态 |
|------|--------|--------|:--:|
| Scaffolding（项目初始化）| `Archon/.archon-src/prompts/prover-autoformalize.md` | `phase3_archon_scaffolding.py` → references + lake init + autoformalize | ✅ |
| Proving（填 sorry）| Plan Agent + Lean Agent + parallel | Phase 4 plan → lean → reviewer → review loop | ✅ |
| Polish（验证/清理/导出）| `Archon/.archon-src/prompts/prover-polish.md` | `phase5_polish.py` → sorry scan + compile check + polish + export | ✅ |

### D. DeerFlow 基础设施复用

| 能力 | 规范要求 | 实现 | 状态 |
|------|---------|------|:--:|
| Agent runtime | DeerFlow agent > 裸 model.invoke() | `create_deerflow_agent()` + `RuntimeFeatures` | ✅ |
| Sandbox | 统一 `sandbox provider` | `config.yaml` local sandbox | ✅ |
| File I/O | `workspace/uploads/outputs` 语义 | Phase 1 `bootstrap_layout` + `/mnt/user-data/` | ✅ |
| Tools | `get_available_tools()` 统一聚合 | Phase 4 Lean tools 已优先走聚合；Phase 2 skill tools 仍有局部直绑 | 🔶 |
| MCP | 统一 MCP 配置 | 配置存在，但部分检索仍通过自管 HTTP 调用而非 DeerFlow MCP 主路径 | 🔶 |
| Checkpointer | SqliteSaver | `_memory_checkpointer()` 优先 `SqliteSaver`，不可用时回退 `MemorySaver` | ✅ |
| Subagent | DeerFlow subagent execution | Phase 2/4 `RuntimeFeatures(subagent=True)` | ✅ |
| Middleware | LoopDetection / ToolError / Clarification | 仅部分节点通过 DeerFlow runtime 间接受益，未见统一显式接线证据 | 🔶 |
| Memory | 双层 memory（DeerFlow + problem）| DeerFlow `MemoryMiddleware` + `rethlas_memory/` + `archon/` | ✅ |
| Run events/history | 与 proof journal 对齐 | 已建立 thread-scoped persistent runtime event log，Phase 5 从该日志做 history alignment | ✅ |

### E. 搜索与可信度

| 能力 | 原实现 | 新实现 | 状态 |
|------|--------|--------|:--:|
| Mathlib 本地搜索 | `search_mathlib.sh` (ripgrep, 3 modes) | `_search_mathlib_local` (ripgrep, 3 modes) | ✅ |
| LeanSearch API | `smart_search.sh` | `_search_leansearch_api` | ✅ |
| Loogle API | `smart_search.sh` | `_search_loogle_api` | ✅ |
| arXiv 搜索 | Rethlas `search_arxiv_theorems` MCP | Matlas API (matlas.ai) → 数学文献 | ✅ |
| Web 搜索回退 | Rethlas built-in web search | Tavily / DuckDuckGo | ✅ |
| 可信度分析 | —（新增）| `_assess_credibility` → Mathlib 10/10, DOI paper 9/10, book 7/10, web 2-4/10 | ✅ |
| 验证驱动搜索 | —（新增）| `search_and_verify` + `verify_theorem` → 不可信结果触发独立证明 | ✅ |

### F. 端到端交付

| 能力 | 状态 |
|------|:--:|
| `scripts/prove.py` 命令行工具 | ✅ |
| Docker Compose 运行（nginx+frontend+gateway）| ✅ |
| Python SDK 直接调用（全 5 Phase 串联）| ✅ |
| Gateway REST API 调用 | 🔶（健康检查路径有验证，但未证明全流程论文能力） |
| 测试套件（现 21 项）| ✅（结构测试通过） |

---

## 剩余差距

| 差距 | 优先级 |
|------|:------:|
| Phase 2 repair loop 已补齐，但 skills 与 verification 输出尚未稳定写满各 memory channel，仍需继续固化 | 🔴 |
| Phase 2 skill tools 已具备 channelized memory side effects，但 generation agent 对这些 skills 的实际调用质量仍依赖模型行为 | 🟡 |
| Phase 2 theorem retrieval 仍有部分自管 HTTP 检索路径作为 fallback，尚未完全收敛到 DeerFlow MCP / tool registry 主路径 | 🟡 |
| Phase 3 autoformalize JSON 解析稳健性（当前 fallback 生成占位骨架，强数学命题可能丢失结构）| 🟡 |
| `lake build` 数学库下载（首次需要网络下载 Mathlib，可能超时）| 🟢 |
| Lean LSP 全部接口（当前 6 个 CLI 工具，MCP 级别的 `lean_hammer_premise`、`lean_state_search` 未实现）| 🟢 |
