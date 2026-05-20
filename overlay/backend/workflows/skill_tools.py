"""
Rethlas 自适应技能 Tools — 10 个 LangChain tool，供 create_deerflow_agent 自适应调用

每个 skill 对应原版 Rethlas agents/generation/.agents/skills/ 下的一个 Skill。
Agent 通过 model.bind_tools() 自评估当前状态后动态选择调用哪个 tool，
实现原版 Rethlas 的 "Assess → Choose → Act → Persist" 自适应控制循环。
"""

from langchain.tools import tool
import json

# ═══════════════════════════════════════════════════════════════════════
# Skill 1: obtain-immediate-conclusions
# ═══════════════════════════════════════════════════════════════════════

@tool("obtain_immediate_conclusions", parse_docstring=True)
def obtain_immediate_conclusions_tool(
    theorem: str,
) -> str:
    """从命题中直接导出最明显的推理、特例和直接结论。

    当开始一个新问题、新分支、新子目标时使用。
    廉价的早期进展，帮助清理问题表述。

    Args:
        theorem: 定理的完整陈述
    """
    return (
        f"请从以下命题直接导出最明显的推理和结论：\n\n"
        f"{theorem}\n\n"
        f"输出格式：\n"
        f"1. 直接推论（2-4 条最明显的推理）\n"
        f"2. 特殊情况（命题在特殊参数下的表现）\n"
        f"3. 等价表述（命题的等价写法，如有）\n"
        f"4. 如果命题有明显的构造方向，指出它"
    )


# ═══════════════════════════════════════════════════════════════════════
# Skill 2: search-math-results
# ═══════════════════════════════════════════════════════════════════════

@tool("search_mathematical_results", parse_docstring=True)
def search_mathematical_results_tool(
    query: str,
    max_results: int = 10,
) -> str:
    """搜索相关数学定理和论文（Matlas 引擎，8.07M peer-reviewed 语句）。

    当需要查找已知结果、相关引理或背景知识时使用。
    作为默认的检索工作流入口。

    Args:
        query: 搜索查询（自然语言或数学陈述）
        max_results: 最大结果数（≥10）
    """
    from .shared import search_matlas
    results = search_matlas(query, max_results=max(max_results, 10))
    if not results:
        return f"未找到 '{query}' 的相关结果。建议尝试 web search 作为 fallback。"
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


# ═══════════════════════════════════════════════════════════════════════
# Skill 3: query-memory
# ═══════════════════════════════════════════════════════════════════════

@tool("query_memory", parse_docstring=True)
def query_memory_tool(
    query: str,
    workspace_path: str = "",
    problem_id: str = "default",
) -> str:
    """搜索 Rethlas 10-channel JSONL memory 中的已有结论、例子、反例、失败路径。

    对应原版 Rethlas 的 memory_search。
    当你想检查之前的结论是否对当前问题有用时使用。
    避免重复已经尝试过的失败路径。

    Args:
        query: 搜索查询（自然语言描述你想要的记忆内容）
        workspace_path: 工作区路径（可选）
        problem_id: 问题标识（默认 "default"）
    """
    if not workspace_path:
        return (
            f"无 workspace_path，无法搜索持久化 memory。"
            f"请在上下文中检查以下内容（对应 query: {query}）："
            f"1. 之前的结论是否有可复用的？"
            f"2. 之前的失败路径是否应避免？"
            f"3. 之前的例子/反例是否能提供洞察？"
        )
    try:
        from .shared import search_rethlas_memory
        results = search_rethlas_memory(ws=workspace_path, query=query, problem_id=problem_id)
    except Exception as e:
        return f"搜索 memory 失败: {e}。请基于上下文中的 attempt_history 继续推理。"
    if results.get("total", 0) == 0:
        return f"未在 memory 中找到 '{query}' 的相关记录。请继续推理或尝试其他 skill。"
    lines = [f"找到 {results['total']} 条相关记忆：\n"]
    for channel, data in results.get("results_by_channel", {}).items():
        lines.append(f"## {channel} ({data['count']} 条)")
        for r in data["results"][:3]:
            e = r.get("entry", {})
            rec = e.get("record", {})
            ts = e.get("timestamp_utc", "")[:19]
            lines.append(f"- [{ts}] score={r['score']}: {str(rec)[:250]}")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Skill 4: construct-examples
# ═══════════════════════════════════════════════════════════════════════

@tool("construct_examples", parse_docstring=True)
def construct_examples_tool(
    theorem: str,
    num_examples: int = 3,
) -> str:
    """构造定理的具体例子以验证命题合理性。

    当你在证明中遇到困难、不确定命题是否成立时使用。
    它帮助你通过具体实例检验命题，获得直观认识。

    Args:
        theorem: 定理的完整陈述
        num_examples: 需要构造的例数（默认 3）
    """
    return (
        f"请为以下定理构造 {num_examples} 个具体例子：\n\n"
        f"{theorem}\n\n"
        f"输出格式：对每个例子，说明：\n"
        f"1. 具体对象是什么\n"
        f"2. 命题的假设是否满足\n"
        f"3. 结论是否成立\n"
        f"4. 如有反例迹象，详细说明"
    )


# ═══════════════════════════════════════════════════════════════════════
# Skill 5: construct-counterexamples
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
# Skill 6: propose-decomposition-plans
# ═══════════════════════════════════════════════════════════════════════

@tool("propose_decomposition", parse_docstring=True)
def propose_decomposition_tool(
    theorem_statement: str,
    num_subgoals: int = 3,
) -> str:
    """将主定理分解为多个实质性不同的子目标分解方案。

    当你已经收集了足够的信息（例子、反例、搜索结果、失败经验）时使用。
    提出多个不同方向的分解方案，而不是单一方案。

    Args:
        theorem_statement: 需要分解的定理陈述
        num_subgoals: 每个方案期望的子引理数量（默认 3）
    """
    return (
        f"将以下定理分解为多个不同的子目标方案：\n\n"
        f"{theorem_statement}\n\n"
        f"要求：\n"
        f"1. 提出 2-3 个实质性不同的分解方向（如：代数方向、拓扑方向、组合方向）\n"
        f"2. 每个方向列出 {num_subgoals} 个子引理，按逻辑依赖排序\n"
        f"3. 每个子引理说明：为什么这个方向是合理的，它试图避免哪些已知的失败\n"
        f"4. 输出格式：先分方向，每个方向下列出子引理列表"
    )


# ═══════════════════════════════════════════════════════════════════════
# Skill 7: direct-proving
# ═══════════════════════════════════════════════════════════════════════

@tool("direct_proving", parse_docstring=True)
def direct_proving_tool(
    plan_id: str,
    subgoals: str,
    examples: str = "",
    counterexamples: str = "",
) -> str:
    """对一个分解方案进行直接证明筛选：先尝试证明所有子目标，找出卡点。

    当分解方案被提出后使用。它是一个筛选步骤——
    尝试携带整个方案走一遍，如果卡住了，识别关键卡点。
    不等同于完整证明，而是诊断步骤。

    Args:
        plan_id: 分解方案的标识符
        subgoals: 该方案的子目标列表（JSON 数组格式）
        examples: 可用的相关例子（可选，JSON 数组格式）
        counterexamples: 可用的相关反例（可选，JSON 数组格式）
    """
    return (
        f"## Direct Proving: Plan {plan_id}\n\n"
        f"### 子目标\n{subgoals}\n\n"
        f"{'### 已知例子\n' + examples if examples else ''}"
        f"{'### 已知反例\n' + counterexamples if counterexamples else ''}"
        f"\n"
        f"请对此方案进行直接证明筛选：\n"
        f"1. 按顺序尝试证明每个子目标\n"
        f"2. 对每个子目标，记录状态: solved / partial / blocked\n"
        f"3. 对 blocked 的子目标：为什么卡住？缺少什么？\n"
        f"4. 输出 JSON:\n"
        f'{{"plan_id": "{plan_id}", "status": "solved|partial|blocked",'
        f'"subgoal_results": [{{"subgoal": "...", "status": "solved|partial|blocked", '
        f'"key_stuck_points": ["..."], "used_examples": ["..."], '
        f'"used_counterexamples": ["..."]}}], '
        f'"overall_key_stuck_points": ["..."]}}'
    )


# ═══════════════════════════════════════════════════════════════════════
# Skill 8: recursive-proving (核心 — 多 Proof Plan 并行探索)
# ═══════════════════════════════════════════════════════════════════════

@tool("recursive_proving", parse_docstring=True)
def recursive_proving_tool(
    theorem: str,
    plans_json: str,
    max_concurrent: int = 3,
) -> str:
    """启动多个子 agent，每个按不同的 proof plan 并行探索。

    当所有分解方案已经被 direct-proving 筛选，但无一完全解决时使用。
    这是原版 Rethlas 的核心机制：Plan A/B/C 同时尝试，共享记忆。

    每个子 agent 获得：
    - 完整的定理
    - 分配的 proof plan
    - 该 plan 的卡点
    - 其他 plan 的卡点（避免重复同样错误）
    - 完整的 agent 能力（skills + memory + search）

    Args:
        theorem: 要证明的完整定理陈述
        plans_json: 各 Proof Plan 的 JSON 数组，每项含 plan_id/plan_summary/system_prompt/key_stuck_points
        max_concurrent: 最大并行子 agent 数（默认 3）
    """
    import concurrent.futures
    import logging
    logger = logging.getLogger(__name__)

    try:
        plans = json.loads(plans_json)
    except json.JSONDecodeError:
        return "错误: plans_json 不是有效 JSON。请提供 JSON 数组格式。"

    if not isinstance(plans, list) or not plans:
        return "错误: plans_json 必须是包含至少 1 个 plan 的 JSON 数组。"

    plans = plans[:max_concurrent]
    logger.info("[recursive-proving] 启动 %d 个 proof plan 并行探索", len(plans))

    results = {}
    # 用 ThreadPoolExecutor 并行处理（与 SubagentExecutor 协作）
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(plans), 4)) as pool:
        futures = {}
        for plan in plans:
            plan_id = plan.get("plan_id", f"plan-{len(futures)}")
            plan_summary = plan.get("plan_summary", "")
            stuck_points_self = plan.get("key_stuck_points", [])
            stuck_points_others = plan.get("other_plan_stuck_points", [])
            system_prompt_override = plan.get("system_prompt", "")

            # 构建每个 plan 的任务描述
            task = (
                f"## 目标定理\n{theorem}\n\n"
                f"## 分配的 Proof Plan: {plan_id}\n{plan_summary}\n\n"
                f"## 本 Plan 的已知卡点\n"
                + "\n".join(f"- {sp}" for sp in stuck_points_self) +
                f"\n\n## 其他 Plan 的卡点（供参考，避免重复）\n"
                + "\n".join(f"- {sp}" for sp in stuck_points_others) +
                f"\n\n按照 AGENTS.md 的自适应控制循环执行此 Plan。"
                f"可以自行调用 search / construct-examples / construct-counterexamples 等 skill。"
                f"可以自行 spawn 子 agent。"
                f"将进展和失败写入 memory。"
            )

            futures[plan_id] = pool.submit(
                _run_single_plan,
                plan_id=plan_id,
                task=task,
                system_prompt=system_prompt_override,
            )

        for plan_id, future in futures.items():
            try:
                results[plan_id] = future.result(timeout=1200)
            except concurrent.futures.TimeoutError:
                results[plan_id] = {"status": "timeout", "proof": "", "error": "timeout after 20min"}
            except Exception as e:
                results[plan_id] = {"status": "error", "proof": "", "error": str(e)}

    # 汇总结果
    any_solved = any(r.get("status") == "solved" for r in results.values())
    best_plan = None
    if any_solved:
        best_plan = max(
            [r for r in results.values() if r.get("status") == "solved"],
            key=lambda r: len(r.get("proof", ""))
        )

    return json.dumps({
        "plans_executed": len(plans),
        "results": results,
        "any_solved": any_solved,
        "best_plan_id": best_plan.get("plan_id") if best_plan else None,
        "best_proof": best_plan.get("proof", "") if best_plan else "",
    }, ensure_ascii=False, indent=2)


def _run_single_plan(plan_id: str, task: str, system_prompt: str = "") -> dict:
    """在独立线程中运行单个 proof plan。
    
    注意：此函数不在 LangChain tool 上下文中运行，不能使用 deerflow 全局依赖。
    它直接调 LLM 并在需要时递归。
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from deerflow.models import create_chat_model
        from langchain_core.messages import HumanMessage, SystemMessage

        model = create_chat_model("deepseek-v4", thinking_enabled=True)
        
        sp = system_prompt or (
            "你是 Rethlas 数学证明生成 Agent。你被分配了一个特定的 proof plan。\n"
            "按照 AGENTS.md 的自适应控制循环执行：\n"
            "1. 评估当前状态\n"
            "2. 选择最合适的 skill\n"
            "3. 执行并记录\n"
            "4. 重复直到证明完成或路径耗尽\n\n"
            "输出最终的证明，或如果无法完成，输出关键卡点。"
        )
        
        resp = model.invoke([
            SystemMessage(content=sp),
            HumanMessage(content=task),
        ])
        
        content = str(resp.content)
        # 简单启发式：如果输出很长且不含"sorry"/"unable"/"failed"，可能是有效证明
        if len(content) > 200 and not any(
            kw in content.lower()[:500] 
            for kw in ["unable to prove", "cannot prove", "i failed", "no proof found"]
        ):
            return {"plan_id": plan_id, "status": "solved", "proof": content}
        else:
            return {"plan_id": plan_id, "status": "failed", "proof": content[:500],
                    "error": "未能生成完整证明"}
                    
    except Exception as e:
        logger.warning("[recursive-proving] Plan %s 异常: %s", plan_id, e)
        return {"plan_id": plan_id, "status": "error", "proof": "", "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Skill 9: identify-key-failures
# ═══════════════════════════════════════════════════════════════════════

@tool("identify_key_failures", parse_docstring=True)
def identify_key_failures_tool(
    failure_summary: str,
) -> str:
    """分析多次证明尝试中的共同失败模式。

    当同一问题的多个尝试（包括 recursive-proving 的所有并行方案）都失败时使用。
    总结共同卡点，为下一轮分解方案提供依据。

    Args:
        failure_summary: 所有失败记录的摘要（多方案、多尝试的综合信息）
    """
    return (
        f"分析以下证明失败记录的共同模式：\n\n"
        f"{failure_summary}\n\n"
        f"请分析：\n"
        f"1. 是否有共同的失败原因？（类型错误 / 缺失引理 / 策略方向根本错误）\n"
        f"2. 所有方案共有的根本障碍是什么？\n"
        f"3. 建议下一轮尝试的方向：\n"
        f"   - 哪些方向应该完全放弃？\n"
        f"   - 哪些方向可能值得进一步探索？\n"
        f"   - 是否需要全新的分解方案？\n"
        f"4. 输出 JSON: "
        f'{{"common_failure_modes": ["..."], "root_blocker": "...", '
        f'"plans_to_abandon": ["..."], "plans_to_pursue": ["..."], '
        f'"recommended_next_direction": "..."}}'
    )


# ═══════════════════════════════════════════════════════════════════════
# Skill 10: verify-proof
# ═══════════════════════════════════════════════════════════════════════

@tool("verify_proof", parse_docstring=True)
def verify_proof_tool(
    statement: str,
    proof: str,
) -> str:
    """验证一个完整的候选证明。

    只有当整个问题的完整证明已组装时才调用。
    不要在部分证明或不完整分支上调用。
    验证包括：逻辑有效性、定理应用正确性、引用外部结果的准确性。

    Args:
        statement: 原始命题陈述
        proof: 要验证的完整证明（markdown 格式）
    """
    if not proof.strip():
        return json.dumps({
            "verdict": "wrong",
            "verification_report": {
                "summary": "证明为空",
                "critical_errors": [{"location": "proof", "issue": "证明文本为空"}],
                "gaps": [],
            },
            "repair_hints": "请先生成证明再验证。",
        }, ensure_ascii=False)

    from .shared import make_model, extract_json
    from langchain_core.messages import HumanMessage, SystemMessage

    verifier_prompt = (
        "你是数学证明验证 Agent。检查以下证明的正确性。\n\n"
        "## 验证流程\n"
        "1. 逐语句检查逻辑推理的有效性\n"
        "2. 检查定理引用的正确性\n"
        "3. 检查外部引用的准确性\n"
        "4. 检查缺失的假设和未证明的跳步\n\n"
        "## 裁定规则（严格）\n"
        "- correct ⇔ critical_errors=[] AND gaps=[]\n"
        "- 有任何 error 或 gap → wrong\n"
        "- correct 时 repair_hints=\"\"；wrong 时 repair_hints 非空\n\n"
        "## 输出 JSON\n"
        '{"verification_report":{"summary":"...","critical_errors":[],"gaps":[]},'
        '"verdict":"correct|wrong","repair_hints":"..."}\n'
    )

    resp = make_model().invoke([
        SystemMessage(content=verifier_prompt),
        HumanMessage(content=f"## 命题\n{statement}\n\n## 待验证证明\n{proof}"),
    ])

    verdict = extract_json(str(resp.content))
    if not verdict:
        verdict = {
            "verdict": "wrong",
            "verification_report": {"summary": "无法解析验证输出", "critical_errors": [], "gaps": []},
            "repair_hints": "验证输出格式错误，请重试验证。",
        }
    return json.dumps(verdict, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
# 完整 Tool 列表（10 个 — 对应原版 Rethlas 的 10 个 Skills）
# ═══════════════════════════════════════════════════════════════════════

Rethlas_SKILL_TOOLS = [
    # 原版 Skill 1: obtain-immediate-conclusions
    obtain_immediate_conclusions_tool,
    # 原版 Skill 2: search-math-results
    search_mathematical_results_tool,
    # 原版 Skill 3: query-memory
    query_memory_tool,
    # 原版 Skill 4: construct-toy-examples
    construct_examples_tool,
    # 原版 Skill 5: construct-counterexamples
    construct_counterexamples_tool,
    # 原版 Skill 6: propose-subgoal-decomposition-plans
    propose_decomposition_tool,
    # 原版 Skill 7: direct-proving
    direct_proving_tool,
    # 原版 Skill 8: recursive-proving
    recursive_proving_tool,
    # 原版 Skill 9: identify-key-failures
    identify_key_failures_tool,
    # 原版 Skill 10: verify-proof
    verify_proof_tool,
]
