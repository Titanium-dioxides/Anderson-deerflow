# SMOKE_TEST.md

## 目的

每次代码或关键开发文档更新后，必须执行冒烟测试，确保项目仍具备连续开发所需的最小一致性。

本文档定义冒烟测试规则。

---

## 文档类修改的最小冒烟测试

当本次改动只涉及文档时，至少执行以下检查：

1. 关键文档存在
2. 关键文档标题可被检索
3. 规划文档之间不存在明显断链

### 推荐命令

```bash
test -f DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md
test -f DEVELOPMENT_ROADMAP.md
test -f MIGRATION_LOG.md
test -f SMOKE_TEST_LOG.md
test -f BLOCKERS.md
test -f KNOWLEDGE.md
test -f AUDIT.md
rg -n "^# " DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md DEVELOPMENT_ROADMAP.md MIGRATION_LOG.md SMOKE_TEST.md SMOKE_TEST_LOG.md BLOCKERS.md KNOWLEDGE.md AUDIT.md TODO.md
```

---

## 代码类修改的最小冒烟测试

当修改 workflow / tools / docs 之外的代码时，至少执行：

1. 目标文件可导入/解析
2. 关键命令可运行
3. 与本次改动最接近的最小路径通过

### 最小建议

#### workflow / Python 代码

```bash
python -m py_compile <modified_python_files>
```

#### workflow 结构检查

```bash
rg -n "build_archon_graph|build_unified_graph|create_deerflow_agent|SubagentExecutor" overlay/backend/workflows
```

#### 若改动 DeerFlow workflow 注册

```bash
test -f overlay/backend/langgraph.json
```

---

## 阶段性专项冒烟测试

### 阶段 1：Runtime 骨架

- workspace 可创建
- sandbox I/O 可执行
- workflow 入口可解析

### 阶段 2：Rethlas

- generation/verification 节点可调用
- skills tools 可注册
- recursive proving 不走裸 `model.invoke()` 主路径

### 阶段 3：Scaffolding

- Lean 项目骨架能生成
- 最少一个 `.lean` 文件可落地

### 阶段 4：Archon proving

- Plan Agent / Lean Agent / Review Agent 路由存在
- attempt/completed/failure 状态真实维护

### 阶段 5：Polish / Export

- artifacts 可输出
- 最终检查可运行

---

## 记录要求

每次执行冒烟测试后：

- 结果追加写入 `SMOKE_TEST_LOG.md`
- 若测试失败：
  - 保留辅助测试代码或说明
  - 记录失败原因
  - 同步更新 `BLOCKERS.md` 或 `TODO.md`

