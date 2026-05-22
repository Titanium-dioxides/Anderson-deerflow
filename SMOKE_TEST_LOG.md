# SMOKE_TEST_LOG.md

## 记录格式

```text
YYYY-MM-DD HH:MM TZ | 范围 | 命令 | 结果 | 备注
```

---

2026-05-22 17:39 CST | docs-baseline | `test -f DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md && test -f DEVELOPMENT_ROADMAP.md && test -f MIGRATION_LOG.md && test -f SMOKE_TEST_LOG.md && test -f BLOCKERS.md && test -f KNOWLEDGE.md && test -f AUDIT.md && rg -n "^# " DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md DEVELOPMENT_ROADMAP.md MIGRATION_LOG.md SMOKE_TEST.md SMOKE_TEST_LOG.md BLOCKERS.md KNOWLEDGE.md AUDIT.md TODO.md` | PASS | 连续开发文档基线已补齐，标题与存在性检查通过
2026-05-22 17:39 CST | docs-baseline-recheck | `test -f DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md && test -f DEVELOPMENT_ROADMAP.md && test -f MIGRATION_LOG.md && test -f SMOKE_TEST_LOG.md && test -f BLOCKERS.md && test -f KNOWLEDGE.md && test -f AUDIT.md && rg -n "^# " DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md DEVELOPMENT_ROADMAP.md MIGRATION_LOG.md SMOKE_TEST.md SMOKE_TEST_LOG.md BLOCKERS.md KNOWLEDGE.md AUDIT.md TODO.md` | PASS | 更新 TODO 与日志后复测通过
