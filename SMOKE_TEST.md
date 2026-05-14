# SMOKE_TEST.md — 冒烟测试规范

> 本项目开发准则之一。每次修改代码后必须执行局部冒烟测试。

---

## 原则

1. **每次修改代码后**，在 `git commit` 之前，执行局部冒烟测试
2. 测试范围为本次改动直接影响的所有函数和路径
3. 测试结果记录到 `SMOKE_TEST_LOG.md`
4. **测试通过** → 删除本次测试代码，在日志中记录测试内容与结果
5. **测试失败** → 保留测试代码，在日志中**重点标记**（`❌ FAILED`），修复后再提交

## 冒烟测试范围

| 层级 | 检查内容 | 示例 |
|------|----------|------|
| L0 — 语法 | Python `ast.parse` | 确保文件无语法错误 |
| L1 — 导入 | 模块级 import 不抛异常 | 至少纯 Python 工具函数可导入 |
| L2 — 纯函数 | 输入→输出的逻辑正确性 | `_parse_lean_errors()`, `_extract_goal()`, `_classify_error()` |
| L3 — 集成 | 真实调用路径可用性 | 用测试 .lean 文件验证 `_verify_file()`；测试 `_local_lean_search()` 搜索范围 |
| L4 — 工作流 | 完整图编译 | `build_archon_graph()` 不抛异常（需 deerflow 环境） |

每次 commit 至少覆盖 L0+L1+L2。如果环境允许，覆盖 L3+L4。

## 测试代码管理

- 测试脚本统一放在 `tests/` 目录下
- 测试用 Lean 项目放在 `tests/fixtures/` 下
- 测试通过的代码在提交前清理（删除临时文件和调试 print）
- 失败的测试保留为 `tests/smoke_{descriptive_name}.py`

## 日志格式（SMOKE_TEST_LOG.md）

```markdown
## YYYY-MM-DD HH:MM — commit_hash

### 测试范围
- [L0] 语法检查
- [L1] 导入检查
- [L2] 纯函数测试: ...

### 测试结果
✅ PASS / ❌ FAILED

### 测试详情
- `_extract_goal()`: 测试正常返回签名 → ✅
- `_parse_lean_errors()`: 解析标准错误输出 → ✅
- ...
```
