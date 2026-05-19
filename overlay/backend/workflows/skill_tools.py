"""
Rethlas 自适应技能 Tools — 供 SubagentExecutor 的 LLM 自适应选择

每个 skill 是 DeerFlow 标准 LangChain tool，LLM 根据证明状态动态调用，
实现原版 Rethlas 的"Agent 自问评估 → 动态选择技能"能力。
"""

from langchain.tools import tool


@tool("construct_examples", parse_docstring=True)
def construct_examples_tool(
    theorem: str,
    num_examples: int = 3,
) -> str:
    """构造定理的具体例子以验证命题合理性。

    当你在证明中遇到困难、不确定命题是否成立时使用此工具。
    它帮助你通过具体实例检验命题，获得直观认识。

    Args:
        theorem: 定理的完整陈述
        num_examples: 需要构造的例数（默认 3）
    """
    # 此工具本身不执行计算——LLM 调用它后，
    # 系统提示会指导 LLM 在 tool result 中输出构造的例子
    return (
        f"请为以下定理构造 {num_examples} 个具体例子：\n\n"
        f"{theorem}\n\n"
        f"输出格式：对每个例子，说明：\n"
        f"1. 具体对象是什么\n"
        f"2. 命题的假设是否满足\n"  
        f"3. 结论是否成立\n"
        f"4. 如有反例迹象，详细说明"
    )


@tool("construct_counterexamples", parse_docstring=True)
def construct_counterexamples_tool(
    claim: str,
) -> str:
    """尝试构造反例来测试一个命题或猜想。

    当一个命题感觉不确定、或者你想测试假设是否可以弱化时使用。
    如果在构造反例中遇到障碍，记录障碍点——这通常揭示了证明的关键。

    Args:
        claim: 要尝试推翻的命题陈述
    """
    return (
        f"尝试为以下命题构造反例：\n\n"
        f"{claim}\n\n"
        f"如果找到了反例：说明为什么它是反例，命题的哪个假设被违反。\n"
        f"如果找不到反例：记录你遇到的障碍——这可能是证明的关键。\n"
        f"障碍可能是：某个假设似乎是必须的 / 某个构造步骤总是失败 / 等。"
    )


@tool("propose_decomposition", parse_docstring=True)
def propose_decomposition_tool(
    theorem_statement: str,
    num_subgoals: int = 3,
) -> str:
    """将主定理分解为 2-4 个更小的子引理。

    当直接证明遇到困难时使用。将复杂定理拆分为更简单、可独立验证的子目标。

    Args:
        theorem_statement: 需要分解的定理陈述
        num_subgoals: 期望的子引理数量（默认 3）
    """
    return (
        f"将以下定理分解为 {num_subgoals} 个辅助引理：\n\n"
        f"{theorem_statement}\n\n"
        f"要求：\n"
        f"1. 每个引理应独立可验证\n"
        f"2. 引理间应有清晰的逻辑依赖关系\n"
        f"3. 所有引理组合起来应能完整证明主定理\n"
        f"4. 输出 Lean 4 代码格式，每个引理用 `:= by\\n  sorry` 占位"
    )


@tool("identify_key_failures", parse_docstring=True)
def identify_key_failures_tool(
    failure_summary: str,
) -> str:
    """识别多次证明尝试中的共同失败模式。

    当同一问题的多个尝试都失败时使用。
    分析共同模式、提供改进方向建议。

    Args:
        failure_summary: 失败记录摘要（如 'type mismatch 3次; unknown identifier 2次'）
    """
    return (
        f"分析以下证明失败记录的共同模式：\n\n"
        f"{failure_summary}\n\n"
        f"请分析：\n"
        f"1. 是否有共同的失败原因？（类型错误 / 缺失引理 / 策略方向错误）\n"
        f"2. 最可能的原因是什么？\n"
        f"3. 建议下一步尝试的方向（换策略 / 换模型 / 分解 / 搜索更多引理）"
    )


@tool("search_mathematical_results", parse_docstring=True)
def search_mathematical_results_tool(
    query: str,
    max_results: int = 10,
) -> str:
    """搜索相关数学定理和论文（Matlas 引擎）。

    当需要查找已知结果、相关引理或背景知识时使用。
    搜索 peer-reviewed 论文中的数学陈述（8.07M 条）。

    Args:
        query: 搜索查询（自然语言）
        max_results: 最大结果数（≥10）
    """
    from .shared import search_matlas
    results = search_matlas(query, max_results=max(max_results, 10))
    if not results:
        return f"未找到 '{query}' 的相关结果。"
    lines = [f"找到 {len(results)} 个相关结果：\n"]
    for i, r in enumerate(results[:5]):
        stmt = r.get("statement", "")[:200]
        src = r.get("entity_name", "")
        journal = r.get("journal", "")
        year = r.get("year", "")
        doi = r.get("doi", "")
        info = f"- [{src}] {stmt}"
        if journal:
            info += f" ({journal}, {year})"
        if doi:
            info += f" doi:{doi}"
        lines.append(info)
    return "\n".join(lines)


# ── 全部技能工具列表 ──

Rethlas_SKILL_TOOLS = [
    construct_examples_tool,
    construct_counterexamples_tool,
    propose_decomposition_tool,
    identify_key_failures_tool,
    search_mathematical_results_tool,
]
