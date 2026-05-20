# Archon-DeerFlow 使用教程

> Gateway: `http://localhost:2026` · Status: ✅ Healthy  
> API Key: `sk-fba…82fc` (DeepSeek V4)  
> 最后更新: 2026-05-20

---

## 一、两个工作流

### 1. `archon_workflow` — Lean4 证明填充

**场景：** 你已有 Lean 项目，里面有 `sorry` 需要填充。

```
autoformalize → planner → prover → reviewer → (loop) → polish → review_agent
```

**示例：**

```python
from deerflow.archon_workflow import run_archon_workflow

result = run_archon_workflow(
    "/app/workspace/my-project",   # Lean 项目路径
    max_loops=5,                    # 最大循环次数
    parallel=True,                  # True=并行证明, False=串行
    dry_run=False,                  # True=调试模式(不调LLM)
)
print(result["stage"])       # COMPLETE
print(result["completed"])   # ["path/to/file.lean", ...]
```

### 2. `unified_prover` — 完整数学定理证明

**场景：** 从自然语言命题出发，自动生成证明并形式化为 Lean。

```
search → rethlas_agent (10 tools) → verifier → (loop ≤3) 
       → autoformalize → planner → prover → reviewer → polish → review_agent
```

**示例：**

```python
from deerflow.archon_workflow import run_unified_workflow

result = run_unified_workflow(
    statement="证明: 素数有无穷多个",
    workspace_path="/app/workspace/unified-proof",
    max_loops=5,
    parallel=True,
    dry_run=False,
)
```

---

## 二、REST API 调用

### 触发 `archon_workflow`

```bash
curl -X POST http://localhost:2026/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "archon_workflow",
    "input": {"workspace_path": "/app/workspace/my-project"},
    "config": {"configurable": {"thread_id": "run-001"}}
  }'
```

### 触发 `unified_prover`

```bash
curl -X POST http://localhost:2026/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "unified_prover",
    "input": {
      "statement": "证明: 素数有无穷多个",
      "workspace_path": "/app/workspace/unified-proof"
    },
    "config": {"configurable": {"thread_id": "unified-001"}}
  }'
```

### 查询运行状态

```bash
curl -s http://localhost:2026/runs/unified-001 | python3 -m json.tool
```

---

## 三、在容器内直接调用

```bash
# 进入容器
docker exec -it deer-flow-gateway bash

# 方式 A: Python 直接调用
/app/backend/.venv/bin/python3 -c "
import sys
sys.path.insert(0, '/app/backend/packages/harness')
from deerflow.archon_workflow import run_archon_workflow

result = run_archon_workflow('/app/workspace/test-proof', max_loops=3)
print('Stage:', result['stage'])
print('Completed:', result['completed'])
"

# 方式 B: 创建 Lean 项目然后证明
mkdir -p /app/workspace/prime-test/PrimeTest
cat > /app/workspace/prime-test/PrimeTest/Main.lean << 'EOF'
import Mathlib

theorem add_zero (n : Nat) : n + 0 = n := by
  sorry
EOF

cat > /app/workspace/prime-test/lakefile.toml << 'EOF'
name = "prime-test"
[[lean_lib]]
name = "PrimeTest"
EOF
echo "leanprover/lean4:v4.29.1" > /app/workspace/prime-test/lean-toolchain

/app/backend/.venv/bin/python3 -c "
import sys; sys.path.insert(0, '/app/backend/packages/harness')
from deerflow.archon_workflow import run_archon_workflow
r = run_archon_workflow('/app/workspace/prime-test', max_loops=3)
print('✅', r['stage'])
"
```

---

## 四、创建 Lean 测试项目

```bash
mkdir my-theorem && cd my-theorem && mkdir MyTheorem

# 写入带 sorry 的定理
cat > MyTheorem/Basic.lean << 'EOF'
import Mathlib

theorem add_comm (a b : Nat) : a + b = b + a := by
  sorry

theorem mul_zero (n : Nat) : n * 0 = 0 := by
  sorry
EOF

# 项目配置
cat > lakefile.toml << 'EOF'
name = "my-theorem"
[[lean_lib]]
name = "MyTheorem"
[dependencies]
mathlib = { git = "https://github.com/leanprover-community/mathlib4.git" }
EOF

echo "leanprover/lean4:v4.29.1" > lean-toolchain
```

---

## 五、Dry-Run 调试模式

不调 LLM，只打印 prompt，零 API 费用：

```python
result = run_archon_workflow(
    "/app/workspace/my-project",
    dry_run=True,        # ← 只打印 prompt
)
```

日志中会看到 `[plan] DRY-RUN`、`[prove] DRY-RUN`、`[rethlas-agent] DRY-RUN`。

---

## 六、串行模式

```python
result = run_archon_workflow(
    "/app/workspace/my-project",
    parallel=False,       # ← 文件逐个处理
)
```

适用场景：文件间有依赖、调试时需要精确执行顺序。

---

## 七、查看证明结果

```python
result = run_archon_workflow("/app/workspace/my-project")

# 阶段
result["stage"]           # "COMPLETE" | "PROVER" | "AUTOFORMALIZE"

# 已完成文件
result["completed"]       # ["MyTheorem/Basic.lean", ...]

# 待处理
result["pending"]         # [{"file": "...", "line": "..."}, ...]

# 循环信息
result["loop_count"]      # 实际循环数
result["max_loops"]       # 配置上限

# 审查摘要
result["review"]          # "Build: PASS, sorries: 0, 已完成: 2"

# Rethlas 信息 (仅 unified_prover)
result.get("rethlas_attempts")   # 非形式化证明尝试次数
result.get("rethlas_failed")     # 是否失败
result.get("informal_proof")     # 生成的非形式化证明
```

---

## 八、Journal 和日志

项目运行后自动生成 `.archon-journal/`：

```
/app/workspace/my-project/.archon-journal/
├── PROJECT_STATUS.md              ← 总体进展
├── USER_HINTS.md                  ← 用户提示
├── memory.json                    ← 跨 session 记忆
├── rethlas_memory/{problem_id}/   ← Rethlas 10-channel memory
│   ├── proof_steps.jsonl
│   ├── failed_paths.jsonl
│   └── ...
└── sessions/session_N/
    ├── summary.md                 ← 本次摘要
    ├── milestones.jsonl           ← 里程碑
    └── recommendations.md         ← 建议
```

```bash
# 查看最新 journal
docker exec deer-flow-gateway cat /app/workspace/my-project/.archon-journal/PROJECT_STATUS.md

# 查看 Rethlas memory
docker exec deer-flow-gateway cat /app/workspace/my-project/.archon-journal/rethlas_memory/default/proof_steps.jsonl
```

---

## 九、Web UI

打开 `http://localhost:2026`，在对话窗口直接描述需求。DeerFlow 的 `lead_agent` 会自动判断是否触发 `archon_workflow` 或 `unified_prover`。

---

## 十、10 个 Rethlas 自适应技能

`unified_prover` 的 `rethlas_agent_node` 使用 `create_deerflow_agent()` 绑定 10 个 tool，Agent 自主评估状态后选择：

| # | Tool | 功能 |
|:-:|------|------|
| 1 | `obtain_immediate_conclusions` | 直接推理 |
| 2 | `search_mathematical_results` | Matlas 定理搜索 |
| 3 | `query_memory` | 搜索本地记忆 |
| 4 | `construct_examples` | 构造例子 |
| 5 | `construct_counterexamples` | 构造反例 |
| 6 | `propose_decomposition` | 多方向分解 |
| 7 | `direct_proving` | 直接证明筛选 |
| 8 | `recursive_proving` | 并行 Plan A/B/C |
| 9 | `identify_key_failures` | 总结失败模式 |
| 10 | `verify_proof` | 严格验证 |
