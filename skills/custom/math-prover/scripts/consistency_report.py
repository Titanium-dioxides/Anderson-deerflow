#!/usr/bin/env python3
"""
一致性分析报告生成器 — verifier.md vs Rethlas AGENTS.md
"""
import textwrap

def section(title, items):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    for k, v in items:
        print(f"  {k}: {v}")

# ============================
# verifier.md 一致性矩阵
# ============================
print("""
╔════════════════════════════════════════════════════════════╗
║  Math-Prover Skill 一致性分析                             ║
║  对比基准: Rethlas agents/verification/AGENTS.md + 3 skills ║
╚════════════════════════════════════════════════════════════╝
""")

section("1. verifier.md — 验证步骤映射", [
    ("Rethlas AGENTS.md Step 1", "提取假设 → verifier.md Step 1 ✅ 完全一致"),
    ("Rethlas verify-sequential skills", "逐句审查 → verifier.md Step 2 ✅ 完全一致"),
    ("Rethlas check-referenced skill", "外部引用检查 → verifier.md Step 4 ✅ 核心逻辑保留"),
    ("Rethlas synthesize-verification skill", "聚合+裁定 → verifier.md Step 5-6 ✅ 完全一致"),
])

section("2. 审查标准逐项对比", [
    ("① 逻辑有效性", "Rethlas: 'validity of inferences' / Verifier: '逻辑有效性' ✅"),
    ("② 定理适用性", "Rethlas: 'correct theorem application' / Verifier: '定理适用性' ✅"),
    ("③ 假设完备性", "Rethlas: 'missing assumptions' / Verifier: '假设完备性' ✅"),
    ("④ 推理跳跃", "Rethlas: 'unjustified jumps / hand-wavy' / Verifier: '推理跳跃' ✅"),
    ("⑤ 假设使用审计", "Rethlas: 'check unused assumptions, not assumed harmless' / Verifier: '假设使用审计' ✅"),
    ("⑥ 模糊用语检查", "Rethlas: 隐式 (hand-wavy) / Verifier: 显式禁止'显然' ⚠️ 更严格"),
    ("⑦ 外部引用+定义展开", "Rethlas: 9-step MCP流程 / Verifier: 3步精简版 ⚠️ 实现细节简化"),
])

section("3. JSON Schema 一致性", [
    ("verification_report.summary", "Rethlas: string / Verifier: string ✅"),
    ("critical_errors[].location", "Rethlas: string / Verifier: string ✅"),
    ("critical_errors[].issue", "Rethlas: string / Verifier: string ✅"),
    ("gaps[].location", "Rethlas: string / Verifier: string ✅"),
    ("gaps[].issue", "Rethlas: string / Verifier: string ✅"),
    ("verdict enum", "Rethlas: 'correct'|'wrong' / Verifier: 'correct'|'wrong' ✅"),
    ("repair_hints rule", "Rethlas: correct→'', wrong→non-empty / Verifier: 同 ✅"),
])

section("4. 裁定规则一致性", [
    ("critical_errors=[] AND gaps=[] → correct", "Rethlas: ✅ / Verifier: ✅"),
    ("任意 error/gap → wrong", "Rethlas: ✅ / Verifier: ✅"),
    ("wrong → repair_hints 非空", "Rethlas: ✅ / Verifier: ✅"),
])

section("5. 删减/新增项", [
    ("⚠️ 删除: MCP memory tools", "Rethlas 要求 memory_init/append/write_verification_output — Verifier 已删除 (DeerFlow Skill 不需要 MCP)"),
    ("⚠️ 删除: 3 skill 执行顺序", "Rethlas 要求按顺序调用 3 个子 skill — Verifier 合并为单一流程"),
    ("⚠️ 删除: search_arxiv_theorems fallback 链", "Rethlas 有 2 级 fallback — Verifier 仅保留核心逻辑"),
    ("🔶 新增: 纯 JSON 防污染", "'{' 必须是第一个字符 — 原版无此约束"),
    ("🔶 新增: '显然'类词汇显式封禁", "原版仅说 'hand-wavy'，此处显式列出禁用词"),
    ("🔶 新增: 中文角色卡", "角色扮演语气 (铁面审稿人) — 原版为纯技术文档风格"),
])

print("""
╔════════════════════════════════════════════════════════════╗
║  结论: 核心验证逻辑保留率 ~90%，主要差异在实现层(去MCP化) ║
║  新增约束(显然禁止/JSON防污染)均为增强，不与原版冲突     ║
╚════════════════════════════════════════════════════════════╝
""")
