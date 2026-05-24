># 项目开发准则
## 最高准则
1. 遵循DeerFlow的开发准则，可参考DEERFLOW_REFERENCE.md的内容，确保代码质量和功能完整性.
2. 确保agent编排逻辑符合DeerFlow的规范，避免使用旧版的agent编排逻辑,确保充分使用deerflow基础设置
3. 确保agent 编排逻辑 与/home/zdzdhd/ai4math/Rethlas 两个 /home/zdzdhd/ai4math/Archon
这两个项目的agent编排逻辑保持一致。
4. 确保agent编排逻辑可以满足source_paper.md文件中描述的功能。
## 项目开发准则
>📋 **本项目开发准则：**
> 1. **每次代码修改必须记录在 `MIGRATION_LOG.md`** — 格式: `YYYY-MM-DD: [组件] 改动说明`
> 2. **每次修改代码后必须执行冒烟测试** — 规则见 `SMOKE_TEST.md`
> 3. **测试结果记录在 `SMOKE_TEST_LOG.md`** — 通过则删除测试代码，失败则保留并标记
> 4. **每次修改后必须 `git commit`** — commit message 须包含改动摘要
> 5. **维护 `TODO.md`** — 未完成功能、已知问题、待改进项，按优先级排列。每次发现新问题必须更新
> 6. **维护 `BLOCKERS.md`** — 区分受阻问题（外部依赖/架构限制）与未实现功能。每次解除 blocker 必须记录
> 7. **维护 `KNOWLEDGE.md`** — 记录项目知识
> 8. **维护 `AUDIT.md`** — 详细实现审计报告
