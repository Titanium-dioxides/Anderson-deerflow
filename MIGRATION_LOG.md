# MIGRATION_LOG.md

## 记录格式

```text
YYYY-MM-DD: [组件] 改动说明
```

---

2026-05-22: [规划] 新增 `DEERFLOW_NATIVE_MIGRATION_FRAMEWORK.md`，定义论文对齐且 DeerFlow-native 的迁移规范。
2026-05-22: [规划] 新增 `DEVELOPMENT_ROADMAP.md`，整理分阶段开发路线与阶段性测试门槛。
2026-05-22: [流程] 新增 `SMOKE_TEST.md` 与 `SMOKE_TEST_LOG.md`，建立文档/代码修改后的冒烟测试基线。
2026-05-22: [治理] 新增 `BLOCKERS.md`、`KNOWLEDGE.md`、`AUDIT.md`，用于持续维护受阻项、项目知识与实现审计。
2026-05-22: [治理] 更新 `TODO.md` 顶部执行基线，将后续开发主路线切换到阶段式 DeerFlow-native 重构。
2026-05-22: [清理] 清理旧版分析/比较/审计文档，新增新版 `README.md` 作为开发入口，并保留 `source_paper.md` 作为论文基线。
2026-05-22: [Phase1] 新增 `overlay/backend` 最小 runtime skeleton、`extensions_config.json`、`docker/entrypoint.sh`，启动 DeerFlow-native Phase 1 开发。
2026-05-22: [Phase2] 新增 `overlay/backend/workflows/phase2_rethlas.py`，建立 Rethlas 双代理结构、problem memory channels 与 Phase 2 graph 骨架。
2026-05-22: [Phase2] 新增 `overlay/backend/workflows/rethlas_skill_tools.py`，并将 generation / verification 节点接入 DeerFlow agent runtime。
2026-05-23: [Phase5] 新增 `overlay/backend/workflows/phase5_polish.py`，实现 Phase 5 Polish/Export/Runtime History 完整工作流（8 节点：phase4_sync、sorry/axiom 检查、compile check、polish agent、artifact 打包、outputs 导出、runtime history 对齐、manifest 生成）。注册 graph 入口并补齐 8 个测试用例。
2026-05-23: [Phase6] 新增 `overlay/backend/workflows/phase6_e2e.py`，实现 Phase 6 端到端验收框架：全 5 阶段串联 runner、6 道基准题（SIMPLE/RETRIEVAL/COMPLEX 三类）、每阶段结构不变量校验、benchmark runner。注册 graph 入口并补齐 6 个 E2E 测试用例。
2026-05-23: [Docker] 修复 Dockerfile COPY 路径（统一为 repo-root build context），新增 `docker-compose.yml`、`.dockerignore`、`Makefile`（dev/test/docker 目标）、`scripts/dev.sh`（本地开发服务器）。完善 entrypoint.sh 启动诊断。
2026-05-24: [审计] 修正 `AUDIT.md`、`TODO.md`、`BLOCKERS.md`、`KNOWLEDGE.md` 中过于乐观的完成口径，明确 Phase 2/4/5 的真实差距。
2026-05-24: [Phase2] 为 `phase2_rethlas.py` 增加 generation→verification→repair 闭环、verification 结果解析、problem memory 写回与失败收敛逻辑。
2026-05-24: [Phase2] 为 `rethlas_skill_tools.py` 增加 thread/problem-scoped memory/project 环境绑定，修复 `query_memory` 全局扫描问题。
2026-05-24: [Phase4] 调整 `phase4_archon_proving.py`，使 Lean tools 优先走 DeerFlow `get_available_tools()` 聚合主路径，保留 overlay fallback。
2026-05-24: [测试] 新增 `tests/test_phase2_rethlas.py`，覆盖 repair loop 与 scoped memory 查询。
2026-05-24: [Phase1] 调整 `phase1_runtime.py`，优先接入 `SqliteSaver` 持久 checkpointer，并新增 thread-scoped `runtime/run_history.jsonl` 事件日志。
2026-05-24: [Phase4] 调整 `phase4_archon_proving.py`，移除 `ThreadPoolExecutor` 主导的并行封装，改由 DeerFlow subagent/task 主路径驱动 Lean proving 尝试。
2026-05-24: [Phase5] 调整 `phase5_polish.py`，改为从 thread runtime event log 读取历史并生成对齐报告，不再只靠 phase manifests 拼接 history。
2026-05-24: [测试] 新增 `tests/test_phase1_runtime.py`，并扩展 `tests/test_phase5_polish.py`，覆盖持久 checkpointer 优先策略与 runtime history alignment。
2026-05-24: [Phase2] 调整 `rethlas_skill_tools.py`，使各 Rethlas skill 自行把结构化输出写回 problem memory channels，并优先通过工具入口/Lean theorem search 包装器走检索主路径。
2026-05-24: [测试] 扩展 `tests/test_phase2_rethlas.py`，覆盖 skill→memory channel 写入与 scoped retrieval 行为。
