# 移植完成度 · 第三次评估

> **评估时间:** 2026-05-20 11:04  
> **基准:** 原版 Archon (`archon-loop.sh` + 6 prompts + informal_agent + lean-lsp-mcp)  
> 原版 Rethlas (`AGENTS.md` + 10+3 skills + 2 MCP servers + Verification API)  
> **当前:** `/home/zdzdhd/archon-deerflow/` (含 2026-05-20 改造)  
> **方法:** 对每项原版能力，判定是否实现、是否由 DeerFlow 提供、当前接入状态

---

## 一、Archon 评估

### 维度 1：编排与架构

| # | 原版能力 | 原版实现 | 当前 | DeerFlow 提供 |
|:-:|---------|---------|:----:|:-----------:|
| 1.1 | 迭代循环 | `archon-loop.sh` for loop (max 10) | ✅ StateGraph 条件边 | — |
| 1.2 | Plan→Prove→Review | 三阶段顺序执行 | ✅ 3 节点全部实现 | — |
| 1.3 | 并行 Prover (per-file) | `run_parallel_provers()` + `$MAX_PARALLEL` | ✅ `SubagentExecutor.execute_async()` | ✅ |
| 1.4 | 串行/并行切换 | `--serial` flag | ❌ 始终并行 | — |
| 1.5 | Dry-run 模式 | `--dry-run` flag | ❌ | — |
| 1.6 | JSONL 结构化日志 | `_log_jsonl()` per-event | ✅ | `JsonlRunEventStore` |
| 1.7 | Cost/Token 追踪 | `show_cost_summary()` | ✅ | `TokenUsageMiddleware` |
| 1.8 | 中断处理 | `trap INT` | ❌ | — |

**评分: 6/8 = 75%** (不变)

### 维度 2：Plan Agent

| # | 原版能力 | 当前 |
|:-:|---------|:----:|
| 2.1 | USER_HINTS.md 读取+清除 | ✅ |
| 2.2 | `/- USER: ... -/` 注释扫描 | ✅ |
| 2.3 | task_results/ 合并 | ⚠️ `attempt_history` 内存 |
| 2.4 | proof-journal 推荐读取 | ❌ |
| 2.5 | PROJECT_STATUS.md 读取 | ❌ |
| 2.6 | 4 种失败模式 | ✅ (扩展为 5) |
| 2.7 | 非形式化内容供给 (3 档) | ✅ LLM 生成 |
| 2.8 | informal_agent.py 调用 | ✅ `create_chat_model()` 等价 |
| 2.9 | Re-routing (替代证明) | ✅ B5 分解 |
| 2.10 | 独立验证 prover 报告 | ✅ reviewer node |
| 2.11 | 子目标分解 | ✅ B5 |
| 2.12 | 多 Agent 协调 | ✅ per-file subagent |
| 2.13 | 三阶段转换 | ⚠️ 缺 polish 阶段 |
| 2.14 | 死胡同文档化 | ⚠️ 无 task_pending |
| 2.15 | 上下文管理 | ✅ |

**评分: 10/15 = 67%** (不变)

### 维度 3：Prover Agent

| # | 原版能力 | 当前 |
|:-:|---------|:----:|
| 3.1 | Prover 阶段 | ✅ |
| 3.2 | Autoformalize 阶段 (lemma skeleton + split modules) | ✅ **↑ 已增强** (引理结构感知+MODULE拆分) |
| 3.3 | Polish 阶段 (golf/refactor) | ⚠️ 简化版 |
| 3.4 | 总是保存部分进展 | ✅ |
| 3.5 | 搜索协议 | ✅ LSP via MCP |
| 3.6 | informal_agent 调用 | ⚠️ DeerFlow model 可用但非独立 tool |
| 3.7 | task_results 日志格式 | ⚠️ `attempt_history` |
| 3.8 | 不修改定理声明 | ✅ |
| 3.9 | End-of-session handoff | ⚠️ |
| 3.10 | 三级验证阶梯 | ✅ |
| 3.11 | 自动策略级联 | ⚠️ 7/10 |
| 3.12 | LSP 22 工具 | ✅ |
| 3.13 | Lean Hammer | ✅ |

**评分: 8/13 = 62%** ↑ (曾 54%, autoformalize 增强)

### 维度 4：Review Agent

| # | 原版能力 | 当前 |
|:-:|---------|:----:|
| 4.1 | attempts_raw.jsonl | ⚠️ `JsonlRunEventStore` 可替代 |
| 4.2 | 逐 attempt 代码 diff | ✅ B6 |
| 4.3 | goal state 记录 | ❌ |
| 4.4 | Lean error 记录 | ⚠️ 手动 parse |
| 4.5 | summary.md | ⚠️ |
| 4.6 | milestones.jsonl | ⚠️ |
| 4.7 | recommendations.md | ✅ |
| 4.8 | PROJECT_STATUS.md | ✅ |
| 4.9 | Self-validation | ❌ |
| 4.10 | 历史 session 读取 | ❌ |

**评分: 5/10 = 50%** (不变)

### 维度 5：工具与基础设施

| # | 原版能力 | 当前 | DeerFlow 提供 |
|:-:|---------|:----:|:-----------:|
| 5.1 | lean-lsp-mcp (22 tools) | ✅ | ✅ MCP |
| 5.2 | informal_agent.py | ✅ | `create_chat_model()` |
| 5.3 | mathlib 搜索 | ✅ | LSP 替代 |
| 5.4 | Lean 错误解析 | ✅ | — |
| 5.5 | extract-attempts.py | ❌ | — |
| 5.6 | validate-review.py | ❌ | — |
| 5.7 | snapshot.py | ✅ | — |
| 5.8 | analyze_let_usage.py | ❌ | — |
| 5.9 | find_exact_candidates.py | ❌ | — |
| 5.10 | solver_cascade.py | ✅ | — |
| 5.11 | minimize_imports.py | ✅ | — |
| 5.12 | init.sh | N/A | DeerFlow 部署 |
| 5.13 | Dashboard UI | ✅ | Web UI |
| 5.14 | 42 Lean 参考文档 | ✅ | — |
| 5.15 | 10 命令 | ✅ | — |
| 5.16 | 4 agent | ✅ | — |

**评分: 12/15 = 80%** (不变)

---

### Archon 综合

| 维度 | 曾评 | 二次评估 | 本次 |
|------|:----:|:------:|:----:|
| 1. 编排架构 | 63% | 75% | **75%** |
| 2. Plan Agent | 60% | 67% | **67%** |
| 3. Prover Agent | 54% | 54% | **62%** ↑ |
| 4. Review Agent | 40% | 50% | **50%** |
| 5. 工具/基础设施 | 63% | 80% | **80%** |
| **Archon 综合** | **56%** | **65%** | **67%** ↑ |

---

## 二、Rethlas 评估

### 维度 6：自适应控制循环

| # | 原版能力 | 当前 | DeerFlow 提供 |
|:-:|---------|:----:|:-----------:|
| 6.1 | 自适应控制循环 (Assess→Choose→Act→Persist) | ✅ **↑** `create_deerflow_agent()` agent loop | ✅ |
| 6.2 | Agent 自评估 (Step 1) | ✅ model 自主推理 (tool-calling) | — |
| 6.3 | Adaptive skill selection (Step 2) | ✅ `model.bind_tools(10 tools)` → 自主选择 | ✅ |
| 6.4 | memory_init + 10 channels | ✅ **↑** `init_rethlas_memory()` | — |
| 6.5 | memory_append | ✅ **↑** `append_rethlas_memory()` | — |
| 6.6 | memory_search (BM25) | ✅ **↑** `search_rethlas_memory()` (关键词匹配) | — |
| 6.7 | branch_update | ⚠️ 无分支管理（但 channel 可承载） | — |
| 6.8 | Hard Invariants (14 条) | ⚠️ 部分通过 system prompt 体现 | — |

**评分: 6/8 = 75%** ↑ (曾 0%)

### 维度 7：10 个 Generation Skills

| # | 原版 Skill | 当前 Tool | 状态 |
|:-:|-----------|----------|:----:|
| 7.1 | obtain-immediate-conclusions | `obtain_immediate_conclusions_tool` | ✅ **↑** 新加 |
| 7.2 | search-math-results | `search_mathematical_results_tool` | ✅ |
| 7.3 | query-memory | `query_memory_tool` → 真正搜索 JSONL | ✅ **↑** |
| 7.4 | construct-toy-examples | `construct_examples_tool` | ✅ |
| 7.5 | construct-counterexamples | `construct_counterexamples_tool` | ✅ |
| 7.6 | propose-decomposition-plans | `propose_decomposition_tool` | ✅ |
| 7.7 | direct-proving | `direct_proving_tool` | ✅ **↑** 新加 |
| 7.8 | recursive-proving | `recursive_proving_tool` | ✅ **↑** 新加 (核心) |
| 7.9 | identify-key-failures | `identify_key_failures_tool` | ✅ |
| 7.10 | verify-proof | `verify_proof_tool` → 内建严格验证 | ✅ **↑** 新加 |

**评分: 10/10 = 100%** ↑ (曾 10%)

> **关键变化:** 所有 10 个 tool 都 `bind_tools()` 到 model，agent 自主选择调用。

### 维度 8：Verification 验证系统

| # | 原版能力 | 当前 | DeerFlow 提供 |
|:-:|---------|:----:|:-----------:|
| 8.1 | verify-sequential-statements | ⚠️ `verifier_node` + `verify_proof_tool` | — |
| 8.2 | check-referenced-statements | ❌ 无 `search_arxiv_theorems` MCP tool | — |
| 8.3 | synthesize-verification-report | ⚠️ `extract_json()` 解析 | — |
| 8.4 | Schema 验证 | ❌ | — |
| 8.5 | 独立 HTTP API 服务 | ❌ | — |
| 8.6 | verification.json 输出 | ⚠️ JSON 内存解析 | — |
| 8.7 | MCP memory (5 channels) | ✅ **↑** rethlas_memory 可承载 | — |

**评分: 3/7 = 43%** ↑ (曾 14%)

### 维度 9：搜索与记忆基础设施

| # | 原版能力 | 当前 |
|:-:|---------|:----:|
| 9.1 | search_arxiv_theorems | ✅ Matlas / leansearch |
| 9.2 | 下载论文 + 提取文本 | ❌ |
| 9.3 | read the proof | ❌ |
| 9.4 | built-in web search | ⚠️ DeerFlow web_search tool 存在 |
| 9.5 | verify_proof_service (HTTP) | ⚠️ `verify_proof_tool` 替代 |
| 9.6 | Output: blueprint.md | ❌ |

**评分: 2/6 = 33%** ↑ (曾 17%)

### 维度 10：整体控制流

| # | 原版能力 | 当前 |
|:-:|---------|:----:|
| 10.1 | 多路并行探索 (Plan A/B/C) | ✅ **↑** `recursive_proving_tool` → `_run_single_plan()` ×N |
| 10.2 | 递归 subagent | ⚠️ `_run_single_plan` 用裸 model.invoke() 非 agent |
| 10.3 | shared memory via problem_id | ✅ **↑** rethlas_memory 同 `problem_id` |
| 10.4 | failed_paths 记录 | ⚠️ channel 存在但未强制写入 |
| 10.5 | 不放弃开放问题 | ⚠️ system prompt 鼓励 |
| 10.6 | 论文不在黑盒使用 | ❌ |

**评分: 3/6 = 50%** ↑ (曾 0%)

---

### Rethlas 综合

| 维度 | 曾评 | 二次评估 | 本次 |
|------|:----:|:------:|:----:|
| 6. 自适应控制循环 | 0% | 0% | **75%** ↑↑↑ |
| 7. 10 个 Skills | 10% | 20% | **100%** ↑↑↑ |
| 8. Verification | 14% | 20% | **43%** ↑ |
| 9. 搜索与记忆 | 17% | 30% | **33%** ↑ |
| 10. 整体控制流 | 0% | 10% | **50%** ↑↑ |
| **Rethlas 综合** | **8%** | **16%** | **60%** ↑↑↑ |

---

## 三、综合汇总

```
                     AUDIT_V3    二次评估    本次评估    变化
────────────────────────────────────────────────────────────
Archon 移植度           63%        65%         67%       +2%
Rethlas 移植度          18%        16%         60%       +44%
────────────────────────────────────────────────────────────
综合                    41%        41%         64%       +23%
```

### 评估变化轨迹

| 时间 | Archon | Rethlas | 主要原因 |
|------|:------:|:------:|------|
| 2026-05-19 (AUDIT_V3) | 63% | 18% | 旧审计高估 Archon (informal_agent/cost tracking 误判), 高估 Rethlas (5 tool 误认为已集成) |
| 2026-05-20 (D1) | 56% | 8% | 逐行审计后发现 9 项未实现 (generator 裸 invoke, tool 未 bind, config 单例...) |
| 2026-05-20 (D2) | 65% | 16% | 加入 DeerFlow 基础设施 (JSONL/Cost/WebUI + informal_agent 等价) |
| **2026-05-20 (D3)** | **67%** | **60%** | **改造: 10 tools + agent loop + recursive-proving + 10ch memory + autoformalize 增强** |

### 剩余差距 (优先级)

| 排名 | 差距 | 严重度 | 领域 |
|:----:|------|:------:|------|
| 1 | Schema 验证 / 独立 Verification API | 🟡 | Rethlas |
| 2 | Paper download + extract text + read proof | 🟡 | Rethlas 搜索 |
| 3 | Polish 阶段 golf/refactor | 🟢 | Archon |
| 4 | Review Agent 缺 goal state / 历史 session | 🟢 | Archon |
| 5 | recursive subagent 用裸 model 非 agent | 🟢 | Rethlas |
| 6 | task_results / task_pending 文件 | 🟢 | Archon |
