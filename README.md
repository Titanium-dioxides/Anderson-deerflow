# Archon on DeerFlow — 数学定理证明系统 🏛️🦞

**Rethlas (非形式化推理) + Archon (Lean4 形式化证明)** 的统一数学定理自动证明系统。

## 包含两个工作流

### 1. `archon_workflow` — Lean4 证明填充

```
planner → prover → reviewer → COMPLETE
```

已有 Lean 项目时使用。自动扫描 `sorry` → 调用 DeepSeek 填充 → `lake build` 验证。

### 2. `unified_prover` — 完整数学定理证明

```
用户命题 → Rethlas 生成证明 → 自我验证(≤3轮) → Archon 形式化 → COMPLETE
```

从自然语言命题到 Lean4 形式化证明的全自动闭环。

## 快速开始

```bash
# Lean4 项目证明
from deerflow.archon_workflow import run_archon_workflow
result = run_archon_workflow("/path/to/lean-project")

# 完整数学证明（命题 + Lean 项目）
from deerflow.archon_workflow import run_unified_workflow
result = run_unified_workflow(
    statement="每个自然数加0等于自身",
    workspace_path="/path/to/lean-project",
)
```

## 仓库结构

```
overlay/
├── backend/
│   ├── langgraph.json    ← 3 个图已注册
│   └── workflows/
│       ├── __init__.py
│       ├── archon_graph.py     ← 3 节点 Lean4 证明
│       └── unified_graph.py    ← 7 节点完整系统
├── extensions_config.json      ← lean-lsp MCP
└── skills/custom/
    └── archon-lean4/SKILL.md   ← 纯知识
```
