# SMOKE_TEST_LOG.md — 冒烟测试记录

> 每次修改代码后必须执行局部冒烟测试。记录格式见 `SMOKE_TEST.md`。

---

## 2026-05-14 20:22 — 8c07159

### 测试范围
- [L0] 语法检查：archon_graph.py, unified_graph.py
- [L1/L2] 纯函数测试：`_classify_error()`, `_parse_lean_errors()`, `_extract_goal()`, `_format_errors()`, `_classify_failure()`

### 测试代码
临时脚本 `tests/smoke_phase1_phase2.py`（已删除，测试通过）

### 测试结果
✅ PASS — 42/42 通过，0/42 失败

### 测试详情

| 被测函数 | 用例数 | 关键检查项 | 结果 |
|----------|--------|-----------|:----:|
| `_classify_error()` | 11 | type_mismatch, unknown_identifier, failed_to_synthesize, don_know_how, invalid, syntax_error, ambiguous, type_error, fallback | ✅ |
| `_parse_lean_errors()` | 8 | 双错误解析、多行消息、空输入、单行输入 | ✅ |
| `_extract_goal()` | 7 | theorem/lemma/def 提取、无效行号、不存在文件 | ✅ |
| `_format_errors()` | 4 | 包含错误类型、文件引用、行号、结构化布局 | ✅ |
| `_classify_failure()` | 6 | missing_infrastructure+compilation, typeclass+compilation, wrong_construction, early_stopping, unknown, empty | ✅ |

### 保留的测试工件
- `tests/fixtures/sample.lean` — 可复用的 Lean 测试样本

---

## 2026-05-14 20:24 — (Phase 3 commit)

### 测试范围
- [L0] 语法检查：archon_graph.py, unified_graph.py
- [L1] 常量 + 函数存在性检查
- [L2] 级联逻辑模拟验证

### 测试代码
临时脚本 `tests/smoke_phase3.py`（已删除，测试通过）

### 测试结果
✅ PASS — 26/26 通过

### 测试详情

| 被测函数 | 用例数 | 关键检查项 | 结果 |
|----------|--------|-----------|:----:|
| `_AUTO_TACTICS` 常量 | 3 | 7 个策略，rfl 开头 grind 结尾 | ✅ |
| `_try_tactics_cascade` 逻辑 | 10 | 单双 sorry、策略选择、降级恢复 | ✅ |
| `_try_tactics_cascade_all` 逻辑 | 4 | 连续解决、边界条件 | ✅ |
| 策略可达性 | 7 | 每策略独立测试 | ✅ |
| 函数存在性 | 4 | 两个文件 × 两个函数 | ✅ |

---

## SSOT 记录
- `SMOKE_TEST.md` ⬤ → 冒烟测试规范（项目开发准则）
- `MIGRATION_LOG.md` ⬤ → 代码改动记录（含新准则声明）
- `SMOKE_TEST_LOG.md` ⬤ → 冒烟测试历史记录
