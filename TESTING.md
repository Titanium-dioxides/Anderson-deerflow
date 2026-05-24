# TESTING.md — 测试指南

## 总览

本项目的测试策略分为三层：

| 层级 | 位置 | 目的 |
|------|------|------|
| 单元测试（Phase 节点） | `tests/test_phase3_*.py` ~ `tests/test_phase6_*.py` | 验证每个 graph 节点的行为正确性 |
| 集成测试（结构不变量） | `tests/test_phase6_e2e.py` | 验证全 5 阶段串联后的结构一致性 |
| 冒烟测试 | `SMOKE_TEST.md` + `SMOKE_TEST_LOG.md` | 每次修改后的最小一致性检查 |

---

## 运行测试

```bash
# 全部测试
python3 -m pytest tests/ -q

# 单个阶段
python3 -m pytest tests/test_phase5_polish.py -q

# 单个用例
python3 -m pytest tests/test_phase6_e2e.py::test_phase6_e2e_simple_true -q

# 带输出（调试用）
python3 -m pytest tests/ -v -s
```

---

## 测试架构

### 依赖桩（Dependency Stubs）

本项目依赖 `langgraph`、`langchain_core`、`deerflow` 等外部包，但测试**不安装真实依赖**。每个测试文件通过 `_install_dependency_stubs()` 注入最小化桩：

```python
def _install_dependency_stubs():
    # langgraph.graph → 空 StateGraph 桩
    # langchain_core.messages → HumanMessage 桩
    # langchain.tools → @tool 装饰器桩
    # deerflow.* → 配置 / agent 工厂桩
```

关键原则：
- **桩只覆盖模块导入链**，不模拟完整行为
- 每个测试**显式 monkeypatch** 需要控制的函数（如 `_run_deerflow_agent`、`subprocess.run`）
- 桩安装在 `sys.modules` 中，对后续 `import` 透明

### 模块加载

被测 workflow 模块通过 `importlib` 按需加载，绕过 package 初始化：

```python
def _load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

这允许测试独立加载 phase 模块，而不会触发 `__init__.py` 中的全量 imports。

### Monkeypatch 模式

需要替换的依赖通过 pytest `monkeypatch` 注入到**已加载模块**的属性上：

```python
phase5 = _load_module(...)
monkeypatch.setattr(phase5, "_run_deerflow_agent", lambda *a, **kw: "...")
monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProcess)
```

**不直接 monkeypatch 未导入的原始模块**，因为被测代码持有的是自己的 import 引用。

---

## 测试用例覆盖

### Phase 3 — Archon Scaffolding（2 个用例）

| 测试 | 验证点 |
|------|--------|
| `test_phase3_scaffold_generates_structured_archon_layout` | references 索引、Lean 项目文件生成（lakefile/lean-toolchain/src/）、.archon/ 状态目录、模块拆分、manifest 输出 |
| `test_phase3_fallback_module_is_valid_lean_placeholder` | LLM 返回不可解析 JSON 时，fallback 生成合法 Lean 占位骨架（`def` + `theorem ... sorry`）|

### Phase 4 — Archon Proving Loop（3 个用例）

| 测试 | 验证点 |
|------|--------|
| `test_phase4_proving_loop_records_attempts_and_completes` | 完整 Plan→Lean→Reviewer→Review 循环，多轮后收敛到 COMPLETE，attempt_history/ failure_modes/review_history 真实写入 |
| `test_phase4_proving_loop_fails_after_repeated_dead_end` | 循环达到 max_loops 仍未收敛时 stage=FAILED，dead_end_files 机制生效 |
| `test_phase4_lean_agent_prefers_task_subagent_runtime` | Lean Agent 优先走 `task` subagent runtime，保留 direct-agent fallback，execution_mode 写入 attempt history |

### Phase 5 — Polish / Export（8 个用例）

| 测试 | 验证点 |
|------|--------|
| `test_phase5_full_pipeline_complete` | Phase 4 COMPLETE 输入，全 8 节点运行，sorry_axiom_pass=True，compile_pass=True，outputs 导出，proof journal 写入 |
| `test_phase5_handles_phase4_failure` | Phase 4 FAILED 输入，sorry 未清零，compile 失败，final_verdict=FAIL，pipeline 不中止 |
| `test_phase5_sorry_axiom_check_detects_sorries` | 行级 `sorry`/`axiom` 检测，per-file 报告含行号，空文件安全 |
| `test_phase5_compile_check_captures_errors` | `lake build` 非零返回码，warning 行正确提取 |
| `test_phase5_compile_check_handles_missing_lake` | lake 命令不存在时 FileNotFoundError 被捕获，返回友好错误消息 |
| `test_phase5_polish_agent_fallback_on_bad_json` | polish agent 输出不可解析时，fallback 字典接管，pipeline 不中断 |
| `test_phase5_export_creates_outputs` | artifact archive、manifest reports、journal 正确复制到 outputs_root |
| `test_phase5_manifest_generated` | 最终 `phase5_polish.json` 结构完整：7 个 stages、results、summary、next=None |

### Phase 6 — 端到端验收（6 个用例）

| 测试 | 类别 | 验证点 |
|------|------|--------|
| `test_phase6_e2e_simple_true` | SIMPLE | 全 5 阶段串联，所有 Phase 1-5 结构检查通过，E2E report 写入 |
| `test_phase6_e2e_simple_add_zero` | SIMPLE | 算术恒等式，Phase 3 scaffold 检查 >=8 项通过 |
| `test_phase6_e2e_retrieval_even_sum` | RETRIEVAL | 偶数求和问题，Phase 2 非形式化证明闭环、Phase 3 形式化骨架生成均通过 |
| `test_phase6_e2e_complex_list_append` | COMPLEX | 多轮 proving + decomposition：验证 attempt_history 含 reroute、review_history 多轮策略调整 |
| `test_phase6_e2e_structural_invariants` | 全类别 | 三个类别（SIMPLE/RETRIEVAL/COMPLEX）分别运行全量不变量检查，Phase 1-5 各 >=4-10 项通过 |
| `test_phase6_e2e_report_generation` | SIMPLE | E2E report 结构（phase/category/structural_report/per_phase）、benchmark runner 未知问题处理 |

---

## 当前通过率

```
19 passed in 0.08s
```

| 阶段 | 测试文件 | 用例数 |
|------|---------|:------:|
| Phase 3 | `test_phase3_archon_scaffolding.py` | 2 |
| Phase 4 | `test_phase4_archon_proving.py` | 3 |
| Phase 5 | `test_phase5_polish.py` | 8 |
| Phase 6 | `test_phase6_e2e.py` | 6 |

---

## 设计原则

1. **不安装真实依赖** — 所有外部包通过 `sys.modules` 桩提供
2. **独立加载** — 每个 phase 模块通过 `importlib` 独立加载，测试间不污染
3. **显式 monkeypatch** — 需要控制的行为显式注入，不依赖隐式桩行为
4. **临时文件系统** — 使用 pytest `tmp_path` + `ARCHON_DEERFLOW_RUNTIME_ROOT` 环境变量隔离
5. **不调用真实 LLM** — `_run_deerflow_agent` 被 monkeypatch 替代，零 API 费用
6. **不调用真实 `lake`** — `subprocess.run` 被 monkeypatch 替代
