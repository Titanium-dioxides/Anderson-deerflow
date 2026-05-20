---
name: archon-lean4
display_name: Archon Lean4 Base Skill
description: Lean4 语言基础能力，包括诊断、搜索、sorry 分析等。
tags: [archon, lean4, math]
---

# Archon Lean4 基础技能

提供 Lean4 定理证明的基础操作支持。

## 可用命令

| 命令 | 功能 |
|------|------|
| `sorry_analyzer.py` | 分析项目中的 sorry，生成统计报告 |
| `extract-attempts.py` | 提取证明尝试记录 |
| `validate-review.py` | 验证审查结果 |

## 使用规范

- 修改 .lean 文件后必须运行 `lake build` 确认编译通过
- 编译失败后需读取完整错误信息再重新尝试
- 如果连续 3 次相同方向尝试失败，应更换证明策略
