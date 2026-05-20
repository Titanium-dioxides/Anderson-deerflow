# Rethlas 逆向分析记录 (用于 math-prover Skill)

分析日期: 2026-05-08
源码仓库: /home/zdzdhd/ai4math/Rethlas

---

## 1. 架构总览

Rethlas 分为两个主要 Agent:

```
agents/generation/    # 证明生成 — 自适应控制循环
agents/verification/  # 证明验证 — 严格审稿流水线
```

两者通过 MCP 服务和 HTTP API 通信：

```
Generation MCP Server (:8090)              Verification API (:8091)
  ├─ search_arxiv_theorems()      ──→      POST /verify
  ├─ verify_proof_service()                ├─ statement
  ├─ memory_init()                         ├─ proof
  ├─ memory_append()                       └─ Codex CLI subprocess exec
  ├─ memory_search()
  └─ branch_update()
```

### Matlas (外部定理搜索)

```
leansearch.net/thm/search  ← POST {query, task, num_results}
  → 返回 [{title, theorem, arxiv_id, theorem_id}]
```

## 2. 验证标准 (Verification AGENTS.md → verifier.md)

提取自 `agents/verification/AGENTS.md` + 3 个 skill:

| 检查点 | 说明 |
|--------|------|
| 逻辑有效性 | 每步推理必须从前提有效推出结论 |
| 定理适用性 | 引用定理在当前上下文中必须真正适用 |
| 假设完备性 | 所有必要假设是否已显式声明 |
| 推理跳跃 | 不能跳过中间步骤 |
| 假设使用审计 | 命题的假设必须实际在证明中被使用 |
| 模糊用语 | "显然"、"易得"等一律视为 gap |

### 验证输出 Schema

```
{ verification_report: { summary, critical_errors[], gaps[] },
  verdict: "correct" | "wrong",
  repair_hints: "" | "..." }
```

### 裁定规则（严格）

- `correct` ⇔ critical_errors=[] AND gaps=[]
- 有任一 error 或 gap → `wrong`
- `correct` 时 repair_hints=""；`wrong` 时 repair_hints 非空

## 3. 生成策略 (Generation AGENTS.md → generator.md)

Rethlas 生成端是自适应循环，非固定流水线：

1. **Assess state** — 当前进展、卡点、搜索是否充分
2. **Choose next skill** — 从 10 个 skill 中选择：
   - `obtain-immediate-conclusions`, `search-math-results`
   - `query-memory`, `construct-toy-examples`
   - `construct-counterexamples`, `propose-subgoal-decomposition-plans`
   - `direct-proving`, `recursive-proving`
   - `identify-key-failures`, `verify-proof`
3. **Act and persist** — 所有产出写入 memory 通道

DeerFlow 移植后简化为单一生成 prompt + 策略选择指导。

## 4. 关键发现

- Rethlas 依赖 Codex CLI（MCP 客户端）做子代理调度，Verification API 是通过 subprocess 调 Codex exec
- Matlas API (leansearch.net) 需要 User-Agent header，否则返回 403
- Verification 输出通过 `write_verification_output()` 进行 schema 校验后写入 `results/{run_id}/verification.json`
- Generation 端有完整的记忆系统 (memory channels)，DeerFlow 版使用 SKILL.md 的上下文维持状态
