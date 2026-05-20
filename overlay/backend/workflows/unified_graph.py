"""
Unified Math Prover — Rethlas 非形式化证明 → Archon(Lean) 验证
================================================================
Rethlas: create_deerflow_agent() 自适应 agent loop (10 tools, ≤3 repair)
Archon: planner → prover → reviewer

改造 2026-05-20:
- generator_node + verifier_node 固定 pipeline → rethlas_agent_node (create_deerflow_agent)
- Rethlas_SKILL_TOOLS 从 5 个扩展到 10 个
- recursive_proving_tool 支持多 proof plan 并行 subagent
"""

import datetime
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.config.app_config import get_app_config
from deerflow.subagents import SubagentConfig, SubagentExecutor
from deerflow.subagents.executor import (
    SubagentStatus,
    get_background_task_result,
    cleanup_background_task,
)

from .skill_tools import Rethlas_SKILL_TOOLS  # 自适应技能 tools (现已 10 个)

from .shared import (  # E1: 从共享模块导入
    classify_error, parse_lean_errors, format_errors,
    extract_goal, classify_failure,
    make_attempt, extract_code, extract_json,
    AUTO_TACTICS,
    sandbox_context, exec_with_sandbox,
    read_with_sandbox, write_with_sandbox,
    scan_sorries, count_sorries, build_project, verify_file,
    try_tactics_cascade, try_tactics_cascade_all,
    get_model_name, make_model,
    search_matlas,
    get_checkpointer,
    init_rethlas_memory, append_rethlas_memory, search_rethlas_memory,
)

logger = logging.getLogger(__name__)

# B6: 文件快照缓存
_file_snapshots: dict[str, str] = {}

def _snapshot_key(f: str) -> str:
    return f"snapshot-{f}"

def _compute_diff(before: str, after: str) -> str:
    b_lines = before.split('\n')
    a_lines = after.split('\n')
    added = max(0, len(a_lines) - len(b_lines))
    removed = max(0, len(b_lines) - len(a_lines))
    changed = 1 if (before != after and before.strip() and after.strip()) else 0
    return f"+{added} lines, -{removed} lines, changed={changed}"


# ── 路径 ──────────────────────────────────────────────────────────────

_PROJECT_DIR = Path(__file__).parent.parent.parent
_RETHLAS_DIR = _PROJECT_DIR / "skills" / "custom" / "math-prover"
_GEN_PROMPT = str(_RETHLAS_DIR / "prompts" / "generator.md")
_VER_PROMPT = str(_RETHLAS_DIR / "prompts" / "verifier.md")
_SEARCH_URL = "https://leansearch.net/thm/search"


# ── A1/E6: 状态 ────────────────────────────────────────────────────────


def _merge_attempts(existing: list | None, new: list | None) -> list:
    return (existing or []) + (new or [])


def _merge_failure_modes(existing: dict | None, new: dict | None) -> dict:
    merged = dict(existing or {})
    for k, v in (new or {}).items():
        merged[k] = merged.get(k, []) + v
    return merged


class UnifiedState(TypedDict):
    messages: Annotated[list, add_messages]
    statement: str
    thread_id: str
    informal_proof: str
    rethlas_attempts: int
    rethlas_history: list
    rethlas_failed: bool
    workspace_path: str
    stage: Literal["AUTOFORMALIZE", "PROVER", "POLISH", "COMPLETE", "RETHLAS"]
    pending: list
    completed: list
    loop_count: int
    max_loops: int
    review: str
    archon_feedback: str
    archon_outer_cycles: int
    feedback_tier: int  # PR5: 回环策略级别 (0=初始, 1=细化, 2=分解, 3=重路由)
    attempt_history: Annotated[list, _merge_attempts]
    failure_modes: Annotated[dict, _merge_failure_modes]
    informal_hints: dict[str, str]
    previous_strategies: dict[str, list]
    # 1.4/1.5: 运行模式控制
    parallel: bool
    dry_run: bool


def fresh_state(statement: str, ws: str = "", max_loops: int = 5,
               parallel: bool = True, dry_run: bool = False) -> UnifiedState:
    return {
        "messages": [],
        "statement": statement,
        "thread_id": "unified-proof",
        "informal_proof": "",
        "rethlas_attempts": 0,
        "rethlas_history": [],
        "rethlas_failed": False,
        "workspace_path": ws,
        "stage": "RETHLAS",
        "pending": [],
        "completed": [],
        "loop_count": 0,
        "max_loops": max_loops,
        "review": "",
        "archon_feedback": "",
        "archon_outer_cycles": 0,
        "feedback_tier": 0,
        "attempt_history": [],
        "failure_modes": {},
        "informal_hints": {},
        "previous_strategies": {},
        "parallel": parallel,
        "dry_run": dry_run,
    }


# ── 工具函数 ────────────────────────────────────────────────────────────


def _read_prompt(path: str) -> str:
    p = Path(path)
    return p.read_text() if p.exists() else ""


def _extract_proof(text: str) -> str:
    m = re.search(r'<proof>(.*?)</proof>', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _build_skill_prompt(attempts: int, tier: int) -> str:
    """PR4/S1: 根据 proofs 尝试次数和反馈级别动态构建技能提示。"""
    skills = [
        "### 1. 获得直接结论\n从命题中直接导出最明显的推理和特例。"
    ]
    
    if attempts >= 1:
        skills.append(
            "### 2. 构造例子\n"
            "构造命题的具体例子，验证命题的合理性。"
            "如果命题声称对所有对象成立，尝试几个不同类的例子。"
        )
    
    if attempts >= 1:
        skills.append(
            "### 3. 尝试构造反例\n"
            "尝试找到反例。如果在构造反例中遇到障碍，记录障碍点——"
            "这通常揭示了证明的关键困难所在。"
        )
    
    if attempts >= 2:
        skills.append(
            "### 4. 提出子目标分解方案\n"
            "将主定理分解为 2-4 个更小更简单的子引理。"
            "每个子引理应该独立可验证，且逻辑上支持主定理。"
        )
    
    if attempts >= 2 and tier >= 2:
        skills.append(
            "### 5. 识别关键失败\n"
            "回顾前几次失败。识别共同的失败模式：是类型构造错误？"
            "还是缺少必要引理？还是策略方向的根本错误？据此调整方法。"
        )
    
    return "\n".join(skills)


# ── Rethlas 系统提示构建 ────────────────────────────────────────────


def _build_rethlas_system_prompt(state: dict) -> str:
    """构建 Rethlas 自适应 agent 的 system prompt。
    
    优先从 math-prover SKILL.md 加载，回退到内建 prompt。
    注入当前 state 中的上下文（attempt history, feedback tier 等）。
    """
    skill_md = _read_prompt(str(_RETHLAS_DIR / "SKILL.md"))
    if not skill_md:
        skill_md = (
            "# Rethlas 数学证明生成 Agent\n\n"
            "## 自适应控制循环\n"
            "1. **Assess**: 评估当前证明状态——已找到什么？卡在哪？\n"
            "2. **Choose**: 从 10 个 skill 中选择最合适的\n"
            "3. **Act**: 调用选定的 tool 执行\n"
            "4. **Persist**: 记录结果\n"
            "5. **Repeat**: 直到验证通过或所有路径耗尽\n"
        )

    # 注入重试计数和 tier 信息
    attempts = state.get("rethlas_attempts", 0)
    tier = state.get("feedback_tier", 0)
    archon_feedback = state.get("archon_feedback", "")

    context = f"\n\n## 当前状态\n- 尝试次数: {attempts}/3\n"
    if attempts > 0:
        past_verdicts = [
            h.get("verdict", {}).get("verdict", "?")
            for h in state.get("rethlas_history", [])
        ]
        context += f"- 历史裁决: {past_verdicts}\n"
    if archon_feedback:
        fb_short = archon_feedback[:500]
        context += f"- Archon 反馈 (tier {tier}): {fb_short}\n"

    tier_guidance = ""
    if tier == 1:
        tier_guidance = "\n**当前策略: 细化证明** — 提供更详细的步骤。"
    elif tier == 2:
        tier_guidance = "\n**当前策略: 子目标分解** — 将证明拆分为更小的引理。"
    elif tier >= 3:
        tier_guidance = "\n**当前策略: 重路由** — 尝试完全不同的证明方法。"

    return skill_md + context + tier_guidance


# ── Rethlas 节点 ───────────────────────────────────────────────────────


def search_node(state: UnifiedState) -> UnifiedState:
    """G6: 搜索 — Matlas 优先（8M 语句），leansearch.net 回退。"""
    state = dict(state)
    statement = state["statement"]
    logger.info("[search] 搜索: %s", statement[:80])

    results = []
    # 优先 Matlas (8.07M statements from peer-reviewed papers)
    try:
        results = search_matlas(statement, max_results=10)
        if results:
            logger.info("[search] Matlas: %d results", len(results))
    except Exception as e:
        logger.warning("[search] Matlas 失败: %s", e)

    # 回退 leansearch.net (mathlib-only)
    if not results:
        try:
            import ssl, urllib.request
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                _SEARCH_URL,
                data=json.dumps({"query": statement, "task": "retrieve useful theorems", "num_results": 5}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                results = json.loads(resp.read().decode()) if resp.readable() else []
            if results:
                logger.info("[search] leansearch: %d results", len(results))
        except Exception as e:
            logger.warning("[search] leansearch 失败: %s", e)

    search_context = ""
    if results:
        lines = ["## 相关定理（Matlas/leansearch）"]
        for r in results[:8]:
            stmt = r.get("statement", "") or r.get("theorem", "") or r.get("title", "")
            src = r.get("entity_name", "") or ""
            journal = r.get("journal", "") or ""
            year = r.get("year", "") or ""
            do = r.get("doi", "") or ""
            entry = f"- {src}: {stmt}" if src else f"- {stmt}"
            if journal and year:
                entry += f" ({journal}, {year})"
            if do:
                entry += f" [{do}]"
            if len(entry) < 600:
                lines.append(entry)
        search_context = "\n".join(lines)

    state["messages"].append(HumanMessage(
        content=f"用户命题: {statement}\n\n{search_context}\n\n请根据搜索结果生成证明。"
    ))

    # R8: 初始化 Rethlas 10-channel memory
    ws = state.get("workspace_path", "")
    if ws:
        try:
            init_rethlas_memory(ws, problem_id=state.get("thread_id", "rethlas"),
                               meta={"statement": statement[:200]})
        except Exception:
            pass

    return state


def rethlas_agent_node(state: UnifiedState) -> UnifiedState:
    """🤖 自适应 Rethlas Agent — 使用 create_deerflow_agent() 替代固定 pipeline。
    
    原版 Rethlas 的自适应控制循环:
    Assess → Choose skill → Act → Persist → Repeat
    
    现在由 DeerFlow 的 tool-calling agent loop 原生实现：
    Model 收到 messages → 自主决定调用哪个 tool → tool 执行 → 结果返回 → 继续推理
    
    10 个 Rethlas skill 全部 bind 到 model，agent 自评估后动态选择。
    ≤3 轮 repair 由 agent 自主管理（通过 verify_proof_tool 内部验证）。
    """
    state = dict(state)
    statement = state["statement"]
    rethlas_attempts = state.get("rethlas_attempts", 0)
    dry_run = state.get("dry_run", False)

    if rethlas_attempts >= 3:
        logger.info("[rethlas-agent] 已达 3 次上限，停止")
        state["rethlas_failed"] = True
        state["stage"] = "RETHLAS"
        return state

    # 尝试使用 create_deerflow_agent()
    if dry_run:
        logger.info("[rethlas-agent] DRY-RUN: 跳过 LLM 调用")
        logger.info("[rethlas-agent] System prompt (%d chars): %s...", len(system_prompt), system_prompt[:200])
        state["informal_proof"] = "(dry-run)"
        state["rethlas_attempts"] = rethlas_attempts + 1
        state["archon_feedback"] = ""
        return state

    try:
        from deerflow.agents.factory import create_deerflow_agent
        from deerflow.agents.features import RuntimeFeatures
        _HAS_AGENT_FACTORY = True
    except ImportError:
        _HAS_AGENT_FACTORY = False
        logger.warning("[rethlas-agent] create_deerflow_agent 不可用，回退到 model.invoke()")

    system_prompt = _build_rethlas_system_prompt(state)
    
    # 构建初始消息：注入搜索上下文 + 命题 + 生成指引
    base_msg_content = (
        f"## 目标命题\n{statement}\n\n"
        f"请按照自适应控制循环执行证明任务。\n\n"
        f"1. **Assess** 当前状态（搜索已提供相关定理）\n"
        f"2. **Choose** 从 10 个 skill 中选择最合适的\n"
        f"3. **Act** 调用 tool 执行\n"
        f"4. **Persist** 记录进展\n"
        f"5. **Repeat** 直到 verify_proof 通过或 3 次 attempt 用完\n\n"
        f"你可以使用: search_mathematical_results, query_memory, "
        f"obtain_immediate_conclusions, construct_examples, construct_counterexamples, "
        f"propose_decomposition, direct_proving, recursive_proving, identify_key_failures, "
        f"verify_proof.\n\n"
        f"当你认为已经有了一个完整证明时，调用 verify_proof 验证。"
    )

    if _HAS_AGENT_FACTORY:
        try:
            agent = create_deerflow_agent(
                model=make_model(think=True),
                tools=Rethlas_SKILL_TOOLS,
                system_prompt=system_prompt,
                features=RuntimeFeatures(
                    sandbox=False,
                    memory=False,
                    loop_detection=True,
                ),
            )
            result = agent.invoke(
                {"messages": [HumanMessage(content=base_msg_content)]},
                config={"configurable": {"thread_id": state.get("thread_id", "rethlas")}},
            )
            all_messages = result.get("messages", [])
            logger.info("[rethlas-agent] Agent 完成, %d 条消息", len(all_messages))
        except Exception as e:
            logger.warning("[rethlas-agent] create_deerflow_agent 调用失败: %s, 回退", e)
            _HAS_AGENT_FACTORY = False

    if not _HAS_AGENT_FACTORY:
        # 回退：裸 model.invoke()
        resp = make_model(think=True).invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=base_msg_content),
        ])
        all_messages = [resp]
        logger.info("[rethlas-agent] 回退 model.invoke() 完成")

    # 从 agent 输出中提取证明和 verdict
    last_content = ""
    if isinstance(all_messages, list) and all_messages:
        last_msg = all_messages[-1]
        if hasattr(last_msg, 'content'):
            last_content = str(last_msg.content)
    elif hasattr(all_messages, 'content'):
        last_content = str(all_messages.content)
    else:
        last_content = str(all_messages)

    proof = _extract_proof(last_content)
    logger.info("[rethlas-agent] 提取到证明 (%d 字符)", len(proof))

    # 更新 state
    state["informal_proof"] = proof
    state["rethlas_attempts"] = rethlas_attempts + 1
    state["archon_feedback"] = ""

    # R8: 自动持久化 — 保存本轮的 proof 和状态到 rethlas_memory
    ws = state.get("workspace_path", "")
    if ws and proof:
        try:
            append_rethlas_memory(ws, "proof_steps", {
                "attempt": rethlas_attempts + 1,
                "proof_length": len(proof),
            }, problem_id=state.get("thread_id", "rethlas"))
        except Exception as e:
            logger.debug("[rethlas-agent] memory 保存跳过: %s", e)

    return state


def verifier_node(state: UnifiedState) -> UnifiedState:
    """G9: 验证 — 检查 rethlas_agent_node 输出的证明。
    
    注：rethlas_agent_node 内部可以调用 verify_proof_tool 自行验证，
    此节点作为最终 gate（主要在 Archon 反馈回路中使用）。
    """
    state = dict(state)
    proof = state.get("informal_proof", "")

    if not proof.strip():
        state["rethlas_history"].append({
            "attempt": state["rethlas_attempts"],
            "verdict": {"verdict": "wrong", "verification_report": {"summary": "无证明输出", "critical_errors": [], "gaps": []}},
            "proof": "(empty)",
        })
        state["rethlas_failed"] = state["rethlas_attempts"] >= 3
        state["stage"] = "AUTOFORMALIZE" if state["rethlas_attempts"] >= 3 else "RETHLAS"
        return state

    ver_prompt = _read_prompt(_VER_PROMPT)
    if not ver_prompt:
        ver_prompt = (
            "你是数学证明验证 Agent。检查以下证明的正确性。\n\n"
            "## 验证流程\n"
            "1. 逐语句检查逻辑推理的有效性\n"
            "2. 检查定理引用的正确性\n"
            "3. 检查外部引用的准确性\n"
            "4. 检查缺失的假设和未证明的跳步\n\n"
            "## 裁定规则（严格）\n"
            "- correct ⇔ critical_errors=[] AND gaps=[]\n"
            "- wrong 时 repair_hints 非空\n\n"
            "## 输出 JSON\n"
            '{"verification_report":{"summary":"...","critical_errors":[],"gaps":[]},"verdict":"correct|wrong","repair_hints":"..."}\n'
        )

    resp = make_model().invoke([
        SystemMessage(content=ver_prompt),
        HumanMessage(content=f"## 命题\n{state['statement']}\n\n## 待验证证明\n{proof}"),
    ])
    verdict = extract_json(str(resp.content))
    is_correct = verdict.get("verdict") == "correct"
    logger.info("[verify] 判定: %s", "correct" if is_correct else verdict.get("verdict", "unknown"))

    state["rethlas_history"].append({
        "attempt": state["rethlas_attempts"],
        "verdict": verdict,
        "proof": proof[:300],
    })
    state["informal_hints"]["rethlas"] = proof[:2000]

    stage = "AUTOFORMALIZE" if (is_correct or state["rethlas_attempts"] >= 3) else "RETHLAS"
    state["stage"] = stage
    state["rethlas_failed"] = not is_correct and state["rethlas_attempts"] >= 3
    return state


def failure_report_node(state: UnifiedState) -> UnifiedState:
    state = dict(state)
    attempts = state.get("rethlas_history", [])
    lines = [f"# Rethlas 证明失败报告", f"命题: {state['statement']}", f"尝试次数: {len(attempts)}", ""]
    for a in attempts:
        lines.append(f"## Attempt {a['attempt']}")
        lines.append(f"Verdict: {a.get('verdict', {}).get('verdict', '?')}")
        lines.append(f"Proof: {a['proof'][:200]}...\n")
    print("\n".join(lines))
    return state


# ── PR2: Autoformalize 节点 ───────────────────────────────────────────


def autoformalize_node(state: UnifiedState) -> UnifiedState:
    """PR2: autoformalize 阶段 — 将 Rethlas 非形式化证明转为 Lean 声明骨架。
    
    原版 Archon 的三阶段之首：
    1. 读取非形式化证明 → 识别引理结构
    2. 按引理拆分为独立的 Lean 声明（含 sorry 占位）
    3. 大证明拆分为多个 .lean 模块文件
    4. 确保文件编译通过（sorries 在即可）
    """
    state = dict(state)
    ws = state["workspace_path"]
    proof = state.get("informal_proof", "")
    statement = state["statement"]

    if not ws:
        logger.info("[autoformalize] 无项目路径，跳过")
        return {**state, "stage": "AUTOFORMALIZE"}

    project_path = Path(ws)
    if not project_path.exists():
        project_path.mkdir(parents=True, exist_ok=True)

    # 检查是否已有 .lean 文件（已 autoformalize 过）
    lean_files = list(project_path.glob("*.lean")) + list(project_path.glob("**/*.lean"))
    lean_files = [f for f in lean_files if '.lake' not in str(f)]

    if lean_files and proof:
        # 已有文件但有新证明 → 追加（不覆盖）
        logger.info("[autoformalize] 已有 %d 个 .lean 文件", len(lean_files))
        return {**state, "stage": "AUTOFORMALIZE"}

    if not proof:
        logger.warning("[autoformalize] 无非形式化证明，跳过")
        return {**state, "stage": "AUTOFORMALIZE"}

    # Step 1: 分析非形式化证明中的引理结构
    logger.info("[autoformalize] 分析引理结构...")
    analysis_prompt = (
        f"分析以下非形式化证明，列出其中所有的引理/子证明结构。\n\n"
        f"## 命题\n{statement}\n\n"
        f"## 证明\n{proof[:6000]}\n\n"
        f"请输出 JSON 格式，列出：\n"
        f'{{"lemmas": [{{"name": "建议的引理名", "statement": "引理陈述", '
        f'"dependencies": ["依赖的其他引理名"], '
        f'"is_main_theorem": false}}], '
        f'"main_theorem": {{"name": "主定理名", "statement": "..."}}, '
        f'"suggested_imports": ["Mathlib", "..."]}}'
    )

    try:
        resp = make_model().invoke([
            SystemMessage(content="你是 Lean4 形式化专家。分析非形式化证明中的引理结构。"),
            HumanMessage(content=analysis_prompt),
        ])
        structure = extract_json(str(resp.content))
    except Exception as e:
        logger.warning("[autoformalize] 引理分析失败: %s，使用单文件模式", e)
        structure = {}

    lemmas = structure.get("lemmas", [])
    has_lemmas = len(lemmas) > 0
    logger.info("[autoformalize] 检测到 %d 个引理", len(lemmas))

    # Step 2: 生成 Lean 声明骨架
    code_prompt = (
        f"你是一个 Lean4 形式化专家。将以下数学命题和证明翻译为 Lean 4 代码。\n\n"
        f"## 命题\n{statement}\n\n"
    )

    if has_lemmas:
        code_prompt += (
            f"## 引理结构\n以下引理需要在主定理之前声明，每个用 `:= by\n  sorry` 占位。\n"
            f"引理应按依赖顺序排列（被依赖的在前）。\n\n"
        )
        for i, lem in enumerate(lemmas):
            name = lem.get("name", f"lemma_{i+1}")
            stmt = lem.get("statement", "")
            deps = lem.get("dependencies", [])
            code_prompt += f"### 引理: {name}\n{stmt}\n"
            if deps:
                code_prompt += f"依赖: {', '.join(deps)}\n"
            code_prompt += "\n"

    code_prompt += (
        f"\n## 非形式化证明 (供参考)\n{proof[:6000]}\n\n"
        f"## 输出要求\n"
        f"1. 生成一个完整的 .lean 文件\n"
        f"2. 包含正确的 imports（优先使用 Mathlib）\n"
        f"3. 所有引理按依赖顺序排列\n"
        f"4. 主定理在最后\n"
        f"5. 每个证明体用 `:= by\n  sorry` 占位\n"
        f"6. 类型签名准确，符合 Mathlib 风格\n"
        f"7. 如果有多个独立模块（>200 行），用 `/- MODULE: name -/` 注释标记模块边界\n"
    )

    try:
        resp = make_model().invoke([
            SystemMessage(content="你是 Lean4 形式化专家。将数学命题翻译为声明骨架并保留引理结构。"),
            HumanMessage(content=code_prompt),
        ])
        code = extract_code(str(resp.content))
    except Exception as e:
        logger.exception("[autoformalize] LLM 生成失败: %s", e)
        return {**state, "stage": "AUTOFORMALIZE"}

    if not code or len(code) < 50:
        logger.warning("[autoformalize] 生成的代码过短或为空")
        return {**state, "stage": "AUTOFORMALIZE"}

    # Step 3: 按模块边界拆分
    modules = []
    module_pattern = re.compile(r'/\-\s*MODULE:\s*(.+?)\s*\-/')
    parts = module_pattern.split(code)
    if len(parts) > 1:
        # 有显式 MODULE 标记
        # parts[0] = 模块前的 imports/代码
        for i in range(1, len(parts), 2):
            module_name = parts[i].strip().replace(' ', '_')
            module_body = parts[i + 1] if i + 1 < len(parts) else ""
            modules.append((module_name, module_body))
        logger.info("[autoformalize] 检测到 %d 个模块", len(modules))
    else:
        modules.append(("Main", code))

    # Step 4: 写入文件
    main_file = project_path / "Main.lean"
    if len(modules) == 1:
        main_name, main_code = modules[0]
        main_file.write_text(main_code)
        logger.info("[autoformalize] 写入 %s (%d 字符)", main_file, len(main_code))
    else:
        # 多模块: Main.lean import 其他模块
        imports = [
            f"import {project_path.name}.{name}"
            for name, _ in modules if name != "Main"
        ]
        main_code = next((body for name, body in modules if name == "Main"), "")
        if main_code:
            main_file.write_text("\n".join(imports) + "\n\n" + main_code)
        else:
            main_file.write_text("\n".join(imports) + "\n\n")
        logger.info("[autoformalize] 写入 %s (imports: %s)", main_file, imports)
        
        for mod_name, mod_code in modules:
            if mod_name == "Main":
                continue
            mod_file = project_path / f"{mod_name}.lean"
            mod_file.write_text(mod_code)
            logger.info("[autoformalize] 写入 %s (%d 字符)", mod_file, len(mod_code))

    # Step 5: 确保 lakefile 存在
    lakefile = project_path / "lakefile.toml"
    if not lakefile.exists():
        lakefile_text = (
            '[package]\n'
            'name = "' + project_path.name + '"\n'
            'version = "0.1.0"\n'
            '\n'
            '[[lean_lib]]\n'
            'name = "' + project_path.name + '"\n'
            '\n'
            '[dependencies]\n'
            'mathlib = { git = "https://github.com/leanprover-community/mathlib4.git" }\n'
        )
        lakefile.write_text(lakefile_text)
        logger.info("[autoformalize] 创建 %s", lakefile)

    return {**state, "stage": "AUTOFORMALIZE"}


# ── PR3: Polish 节点 ───────────────────────────────────────────────────


def polish_node(state: UnifiedState) -> UnifiedState:
    """PR3: Polish 阶段 — 最终检查、清理、golf、refactor。
    
    原版 Archon 的 Polish 阶段:
    1. 确认 0 sorry + 编译通过
    2. Golf 证明（精简冗余）
    3. Refactor: 提取可复用 helper 到 Mathlib 风格
    4. minimize_imports
    5. 最终编译 + 里程碑验证
    """
    state = dict(state)
    ws = state["workspace_path"]
    if not ws or not Path(ws).exists():
        return state

    logger.info("[polish] 最终检查和清理")

    with sandbox_context(state.get("thread_id", "unified")) as sb:
        ok, log = build_project(ws, sb)
        n = count_sorries(ws, sb)

    logger.info("[polish] lake build: %s, sorries: %d", "PASS" if ok else "FAIL", n)

    if not ok:
        logger.warning("[polish] 编译失败，跳过清理")
        return {**state, "review": state.get("review", "") + f"\n[polish] 最终编译: FAIL"}

    # 尝试 minimize imports
    try:
        minimize_script = Path(__file__).parent.parent.parent / "skills" / "custom" / "archon-lean4" / "scripts" / "minimize_imports.py"
        if minimize_script.exists():
            logger.info("[polish] 运行 minimize_imports")
            exec_with_sandbox(f"python3 {minimize_script} {ws}", ws, sb)
    except Exception as e:
        logger.warning("[polish] minimize_imports 失败: %s", e)

    return {**state, "review": state.get("review", "") + f"\n[polish] 最终编译: PASS, {n} sorries"}


# ── Archon 节点 ─────────────────────────────────────────────────────────


def planner_node(state: UnifiedState) -> UnifiedState:
    """
    PR1: Plan Agent — LLM 驱动（与 archon_graph.py 同步）。
    P2: 读取 USER_HINTS.md 注入上下文。
    P3: 扫描 .lean 文件中的 /- USER: ... -/ 注释。
    """
    ws = state["workspace_path"]
    if not ws:
        return {**state, "stage": "COMPLETE"}

    loop = state.get("loop_count", 0) + 1
    logger.info("[plan-node] === loop #%d ===", loop)

    with sandbox_context(state.get("thread_id", "unified")) as sb:
        sorries = scan_sorries(ws, sb)
    logger.info("[plan-node] %d sorries found", len(sorries))

    if not sorries:
        return {**state, "loop_count": loop, "stage": "COMPLETE"}

    # 分析 attempt_history 失败模式
    all_attempts = state.get("attempt_history", [])
    failure_modes = {}
    previous_strategies = {}
    for s in sorries:
        fn = s["file"]
        file_attempts = [a for a in all_attempts if a["file"] == fn]
        if not file_attempts:
            continue
        previous_strategies[fn] = list({a.get("strategy", "?") for a in file_attempts})
        recent = file_attempts[-3:]
        modes = set()
        for a in recent:
            for m in classify_failure(a):
                modes.add(m)
        failure_modes[fn] = list(modes)
        if modes:
            logger.info("[plan-node] %s: 失败模式 %s", fn, modes)

    # P2: USER_HINTS.md
    hints_path = Path(ws) / ".archon-journal" / "USER_HINTS.md"
    user_hints = ""
    if hints_path.exists():
        user_hints = hints_path.read_text().strip()
        if user_hints:
            logger.info("[plan-node] 读取 USER_HINTS.md")

    # P3: /- USER: ... -/ 注释扫描
    lean_user_comments = {}
    for s in sorries:
        fn = s["file"]
        content = Path(ws, fn).read_text() if Path(ws, fn).exists() else ""
        for m in re.finditer(r'/-\s*USER:?(.*?)-/', content, re.DOTALL):
            comment = m.group(1).strip()
            if comment:
                line_before = content[:m.start()].count("\n") + 1
                lean_user_comments[fn] = f"[行 {line_before}] User 注释: {comment[:500]}"

    # Rethlas 非形式化证明注入
    informal_hints = dict(state.get("informal_hints", {}))
    rethlas_proof = state.get("informal_proof", "")
    if rethlas_proof:
        for s in sorries:
            fn = s["file"]
            if fn not in informal_hints:
                informal_hints[fn] = rethlas_proof[:500]

    # P1: LLM 驱动规划
    needs_llm = bool(user_hints) or bool(all_attempts)
    if needs_llm:
        # B5: 检测需要分解的复杂定理
        for s in sorries:
            fn = s["file"]
            file_attempts = [a for a in all_attempts if a["file"] == fn]
            if len(file_attempts) < 2:
                continue
            if all(a.get("result") in ("abandoned", "error", "timed_out") for a in file_attempts):
                file_path = Path(ws, fn)
                if not file_path.exists():
                    continue
                content_lines = file_path.read_text().split("\n")
                target_line = int(s["line"]) if s["line"].isdigit() else 0
                gs = extract_goal(content_lines, target_line).get("signature", "")
                if len(gs) < 50:
                    continue
                decomp_prompt = (
                    f"你是一个 Lean4 形式化专家。以下定理多次证明失败：\n\n"
                    f"```lean\n{gs[:800]}\n```\n\n"
                    f"失败模式: {', '.join(failure_modes.get(fn, ['unknown']))}\n"
                    f"已尝试: {', '.join(previous_strategies.get(fn, ['?']))}\n\n"
                    f"请将这个定理分解为 2-4 个辅助引理。"
                    f"输出 Lean 代码，每个辅助引理用 `:= by\n  sorry` 占位。"
                )
                try:
                    resp = make_model().invoke([
                        SystemMessage(content="你是 Lean4 形式化专家。将复杂定理分解为子引理。"),
                        HumanMessage(content=decomp_prompt),
                    ])
                    sub_lemmas = extract_code(str(resp.content))
                    if sub_lemmas and len(sub_lemmas) > 100:
                        insert_pos = max(0, target_line - 1)
                        all_l = (content_lines[:insert_pos]
                            + ["", "/- B5: 子目标分解 (自动生成) -/", ""]
                            + sub_lemmas.split("\n") + [""]
                            + content_lines[insert_pos:])
                        file_path.write_text("\n".join(all_l))
                        logger.info("[plan-node] B5: %s 已分解 (%d 行)", fn, len(sub_lemmas.split("\n")))
                except Exception as e:
                    logger.warning("[plan-node] B5: %s 分解失败: %s", fn, e)

        plan_lines = [
            "你是 Archon Plan Agent。分析当前证明状态并生成非形式化指引。",
            "",
            f"## 循环 #{loop}",
            f"项目路径: {ws}",
            "",
            "## 待处理 sorries",
        ]
        for s in sorries:
            fn = s["file"]
            modes = failure_modes.get(fn, [])
            strategies = previous_strategies.get(fn, [])
            user_c = lean_user_comments.get(fn, "")
            plan_lines.append(f"- {fn}:{s['line']}")
            if modes:
                plan_lines.append(f"  失败模式: {', '.join(modes)}")
            if strategies:
                plan_lines.append(f"  已尝试: {', '.join(strategies)}")
            if user_c:
                plan_lines.append(f"  {user_c}")

        if user_hints:
            plan_lines.extend(["", "## 用户提示", user_hints])

        plan_lines.extend([
            "",
            "## 输出要求",
            "对每个文件生成简短的非形式化证明指引（1-3 句）。",
            "格式：每行一个文件，用 | 分隔文件路径和指引。",
        ])

        try:
            resp = make_model().invoke([
                SystemMessage(content="你是 Archon Plan Agent。分析证明状态，提供指引。"),
                HumanMessage(content="\n".join(plan_lines)),
            ])
            plan_text = str(resp.content)
            for line in plan_text.split("\n"):
                if "|" in line:
                    parts = line.split("|", 1)
                    fn_candidate = parts[0].strip().rstrip(":")
                    hint = parts[1].strip()
                    if hint and len(hint) > 10:
                        clean = re.sub(r'^\d+[.\\)\\s]*', '', hint)
                        if clean:
                            informal_hints[fn_candidate] = clean[:500]
                            logger.info("[plan-node] 指引 %s: %s", fn_candidate, clean[:80])
        except Exception as e:
            logger.warning("[plan-node] LLM 规划失败: %s", e)

    return {
        **state,
        "loop_count": loop,
        "failure_modes": failure_modes,
        "previous_strategies": previous_strategies,
        "informal_hints": informal_hints,
        "pending": sorries,
        "stage": "PROVER",
    }


# ── D1: Subagent 配置 ──────────────────────────────────────────────────


def _build_prover_prompt() -> str:
    """P1: 优先 apply_prompt_template，回退手动 prompt。"""
    try:
        from deerflow.agents.lead_agent.prompt import apply_prompt_template
        return apply_prompt_template(
            subagent_enabled=False,
            available_skills=set(["archon-lean4"]),
        )
    except Exception:
        pass
    return ""


UNIFIED_PROVER_CONFIG = SubagentConfig(
    name="unified-prover",
    description="填充 Lean 文件中的 sorry 并编译验证",
    system_prompt=_build_prover_prompt() or "你是 Lean4 形式化证明助手。\n\n"
        "你的任务是：\n"
        "1. 用 `read_file` 读取文件内容\n"
        "2. 用 `lean_goal` 获取编译时目标状态\n"
        "3. 用 `lean_local_search` 搜索相关引理\n"
        "4. 用 `write_file` 写入证明代码（只修改 `sorry` 区域）\n"
        "5. 用 `lean_verify` 编译验证\n"
        "6. 如果失败，检查 `lean_diagnostic_messages` 并修复\n"
        "7. 所有 sorry 通过后，输出最终文件内容。",
    tools=None,
    disallowed_tools=["task", "ask_clarification"],
    model="inherit",
    max_turns=30,
    timeout_seconds=600,
)


def _spawn_prove_subagent(executor: SubagentExecutor, t: dict, state: UnifiedState) -> str | None:
    ws = state["workspace_path"]
    f = t["file"]
    line = t.get("line", "?")
    hints = state.get("informal_hints", {})
    failure_modes = state.get("failure_modes", {})
    loop_count = state["loop_count"]

    with sandbox_context(state.get("thread_id", "unified")) as sb:
        content = read_with_sandbox(ws, f, sb)
        if not content or "sorry" not in content:
            return None
        cascade_ok, tactics_used = try_tactics_cascade_all(ws, f, sb)
        if cascade_ok:
            logger.info("[prove-node] %s 自动化策略: %s", f, tactics_used)
            return None
        # B6: 文件快照
        _file_snapshots[_snapshot_key(f)] = content
        goal_sig = extract_goal(
            content.split("\n"),
            int(line) if line.isdigit() else 0,
        ).get("signature", "")

    hint = hints.get(f, hints.get("rethlas", ""))
    fail_modes = failure_modes.get(f, [])
    goal_text = f"\n## 目标定理\n```lean\n{goal_sig}\n```" if goal_sig else ""
    hint_text = f"\n## 证明指引\n{hint}" if hint else ""
    fail_text = ""
    if fail_modes:
        mode_advice = {
            "missing_infrastructure": "尝试 induction/recursion 基础方法",
            "typeclass": "显式提供 haveI/letI 实例",
            "wrong_construction": "重新检查类型签名",
            "early_stopping": "分解为更小子目标",
        }
        advices = [mode_advice.get(m, "") for m in fail_modes if m in mode_advice]
        if advices:
            fail_text = f"\n## 历史失败\n避免: {', '.join(fail_modes)}\n建议: {'; '.join(advices)}"

    task_msg = f"请处理 Lean 项目的文件 **{f}**（行 {line}）。{goal_text}{hint_text}{fail_text}"
    tid = f"prove-{Path(f).stem}"
    executor.execute_async(task_msg, task_id=tid)
    return tid


def _collect_prove_result(task_id: str, t: dict, state: UnifiedState, max_wait: int = 660) -> None:
    ws = state["workspace_path"]
    f = t["file"]
    deadline = time.time() + max_wait

    while time.time() < deadline:
        result = get_background_task_result(task_id)
        if result is None:
            break

        if result.status == SubagentStatus.COMPLETED:
            text = result.result or ""
            if text and "sorry" not in text:
                code = extract_code(text)
                if code:
                    write_with_sandbox(ws, f, code)
                logger.info("[prove-node] subagent %s 完成", f)
            else:
                logger.warning("[prove-node] subagent %s 未完成", f)
            cleanup_background_task(task_id)
            return

        if result.status in (SubagentStatus.FAILED, SubagentStatus.TIMED_OUT):
            err = result.error or "unknown error"
            logger.warning("[prove-node] subagent %s %s: %s", f, result.status.value, err[:200])
            cleanup_background_task(task_id)
            return

        if result.status == SubagentStatus.CANCELLED:
            logger.warning("[prove-node] subagent %s 被取消", f)
            cleanup_background_task(task_id)
            return

        time.sleep(2)

    logger.warning("[prove-node] subagent %s 轮询超时 (%ds)", f, max_wait)


def prover_node(state: UnifiedState) -> UnifiedState:
    from deerflow.tools import get_available_tools

    ws = state["workspace_path"]
    pending = state.get("pending", [])
    thread_id = state.get("thread_id", "unified")
    parallel = state.get("parallel", True)
    dry_run = state.get("dry_run", False)

    if not pending:
        return state

    if dry_run:
        logger.info("[prove-node] DRY-RUN: 跳过 %d 个文件", len(pending))
        return state

    logger.info("[prove-node] 处理 %d 个文件 (mode=%s)", len(pending), "parallel" if parallel else "serial")

    all_tools = get_available_tools(subagent_enabled=True)
    executor = SubagentExecutor(config=UNIFIED_PROVER_CONFIG, tools=all_tools, thread_id=thread_id)

    completed = list(state.get("completed", []))
    task_ids = []
    for t in pending:
        f = t["file"]
        if not (Path(ws) / f).exists():
            continue
        tid = _spawn_prove_subagent(executor, t, state)
        if tid:
            if not parallel:
                _collect_prove_result(tid, t, state)
            else:
                task_ids.append((tid, t))

    if parallel:
        for tid, t in task_ids:
            _collect_prove_result(tid, t, state)

    done = set(state.get("completed", [])) | set(completed)
    new_pending = [t for t in pending if t["file"] not in done]
    logger.info("[prove-node] 本轮: %d 完成, %d 剩余", len(done), len(new_pending))
    return {**state, "pending": new_pending}


def reviewer_node(state: UnifiedState) -> UnifiedState:
    """PR5: 回环策略层级递进 — 跟踪 feedback_tier 实现 detail→decompose→reroute。"""
    ws = state["workspace_path"]

    with sandbox_context(state.get("thread_id", "unified")) as sb:
        ok, log = build_project(ws, sb)
        n = count_sorries(ws, sb)

    done_count = len(state.get("completed", []))
    pending_count = len(state.get("pending", []))
    total_attempts = len(state.get("attempt_history", []))

    review = f"Build: {'PASS' if ok else 'FAIL'}, sorries: {n}, 完成: {done_count}, 待处理: {pending_count}, 总尝试: {total_attempts}"
    logger.info("[review-node] %s", review)

    stage = state["stage"]
    tier = state.get("feedback_tier", 0)
    archon_feedback = state.get("archon_feedback", "")
    outer_cycles = state.get("archon_outer_cycles", 0)

    if ok and n == 0:
        stage = "COMPLETE"
        tier = 0
    elif state["loop_count"] >= state["max_loops"]:
        stage = "COMPLETE"

    # PR5: 当编译失败时层级递进
    if not ok and n > 0:
        archon_feedback = log[-2000:] if len(log) > 2000 else log
        stage = "RETHLAS"
        outer_cycles += 1
        tier = min(tier + 1, 3)  # max tier = 3
        logger.info("[review-node] 回环策略 tier=%d (cycle #%d): %s",
                    tier, outer_cycles,
                    {0: "初始", 1: "细化证明", 2: "子目标分解", 3: "重路由"}.get(tier, "?"))

    return {
        **state,
        "review": review + f" [tier={tier}]",
        "stage": stage,
        "archon_feedback": archon_feedback,
        "archon_outer_cycles": outer_cycles,
        "feedback_tier": tier,
    }


def review_agent_node(state: UnifiedState) -> UnifiedState:
    ws = state["workspace_path"]
    if not ws or not Path(ws).exists():
        return state

    loop = state["loop_count"]
    attempts = state.get("attempt_history", [])
    pending = state.get("pending", [])
    completed = state.get("completed", [])
    failure_modes = state.get("failure_modes", {})

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    journal_root = Path(ws) / ".archon-journal"
    session_dir = journal_root / f"session_{loop}"
    session_dir.mkdir(parents=True, exist_ok=True)

    file_groups = {}
    for a in attempts:
        file_groups.setdefault(a["file"], []).append(a)

    all_files = set(file_groups.keys()) | {s["file"] for s in pending} | set(completed)
    milestones = []
    summary_lines = [f"# Session {loop} — 审查报告", "", f"时间: {now}", "## 概览", ""]
    rec_lines = [f"# Session {loop} — 推荐", "## 优先级", ""]

    s_after = len(pending)
    summary_lines.append(f"- 本轮后 sorry: {s_after}")
    summary_lines.append(f"- 完成: {len(completed)}")
    summary_lines.append(f"- 总尝试: {len(attempts)}\n")

    blocked = []
    closest = []
    for fn in sorted(all_files):
        fn_atts = file_groups.get(fn, [])
        fn_modes = failure_modes.get(fn, [])
        is_solved = fn in completed
        if fn_atts:
            last = fn_atts[-1]
            status = "solved" if is_solved else ("blocked" if last.get("result") == "abandoned" else "partial")
        else:
            status = "not_started"

        if is_solved:
            closest.append(fn)
        elif status == "blocked":
            blocked.append(fn)
        else:
            closest.append(fn)

        attempt_details = [
            {"attempt": i + 1, "strategy": a.get("strategy", "?")[:60],
             "lean_error": a.get("lean_error", "")[:300], "result": a.get("result", "?")}
            for i, a in enumerate(fn_atts)
        ]

        next_steps_map = {
            "missing_infrastructure": "尝试 induction/recursion",
            "typeclass": "显式提供 haveI/letI 实例",
            "wrong_construction": "重新检查类型签名",
            "early_stopping": "分解为更小子目标",
        }
        next_steps = next((v for k, v in next_steps_map.items() if k in fn_modes), "继续尝试")
        if status == "solved":
            next_steps = "已验证通过"

        milestones.append({
            "timestamp": now, "status": status,
            "target": {"file": fn},
            "session": {"id": f"session_{loop}", "model": "deepseek-v4"},
            "findings": {"blocker": ", ".join(fn_modes) if status != "solved" else "", "key_lemmas_used": []},
            "attempts": attempt_details, "next_steps": next_steps,
        })

        summary_lines.append(f"### {fn}")
        summary_lines.append(f"- {status} | 尝试: {len(fn_atts)} | 模式: {', '.join(fn_modes) or '无'}")
        for d in attempt_details:
            err = d["lean_error"][:100] if d["lean_error"] else "-"
            summary_lines.append(f"  - Attempt {d['attempt']}: [{d['result']}] {d['strategy']}")
        summary_lines.append("")

        if status in ("blocked", "partial"):
            rec_lines.append(f"### {'❌' if status == 'blocked' else '🔄'} {fn}")
            rec_lines.append(f"- 建议: {next_steps}")

    (session_dir / "summary.md").write_text("\n".join(summary_lines))
    with open(session_dir / "milestones.jsonl", "w") as f:
        for m in milestones:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    if blocked:
        rec_lines.append("\n## 阻塞列表\n" + "\n".join(f"- {fn}" for fn in blocked))
    (session_dir / "recommendations.md").write_text("\n".join(rec_lines))

    status_lines = [
        f"# Project Status ({now})", "",
        f"## 总体进展",
        f"- 总 sorry: {s_after}", f"- 完成: {len(completed)}",
        f"- 总尝试: {len(attempts)}", "",
        f"## 已知阻塞",
    ]
    status_lines += [f"- `{fn}`: {', '.join(failure_modes.get(fn, []))}" for fn in blocked] or ["- (无)"]
    (journal_root / "PROJECT_STATUS.md").write_text("\n".join(status_lines))

    # P2: 写入 USER_HINTS.md
    user_hints_path = journal_root / "USER_HINTS.md"
    if not user_hints_path.exists():
        hints_content = [
            "# USER_HINTS.md — 用户提示",
            "",
            "在下一轮 plan 时，在下方写入你对证明方向的指引。",
            "清空此文件可清除所有提示。",
            "",
            "示例：",
            "- 优先处理 Core.lean 中的 sorry",
            "- 对于 lemma x，尝试用 Finset.sum_comm 替代 ring",
            "- 不要重复尝试类型构造错误: 换一个构造方法",
            "",
        ]
        if blocked:
            hints_content.append("## 已知阻塞（不要重复尝试）")
            for fn in blocked:
                hints_content.append(f"- {fn}: {', '.join(failure_modes.get(fn, []))}")
            hints_content.append("")
        user_hints_path.write_text("\n".join(hints_content))

    logger.info("[review-agent-node] 期刊已写入 %s", session_dir)
    return state


# ── 路由 ──────────────────────────────────────────────────────────────


def route_rethlas_after_agent(state: UnifiedState) -> str:
    """rethlas_agent_node 之后的路由。
    - proof 通过验证 → autoformalize
    - 未通过但 attempt < 3 → rethlas_agent (继续)
    - 3 次全失败 → rethlas_report
    """
    stage = state.get("stage", "")
    if stage == "AUTOFORMALIZE":
        return "autoformalize"
    if state.get("rethlas_failed"):
        return "rethlas_report"
    # 未失败：进入验证节点
    return "verifier"


def route_after_verify(state: UnifiedState) -> str:
    """verifier_node 之后的路由。"""
    stage = state.get("stage", "")
    if stage == "AUTOFORMALIZE":
        return "autoformalize"
    if state.get("rethlas_failed"):
        return "rethlas_report"
    # 仍需要更多 attempt: 回到 rethlas_agent
    return "rethlas_agent"


def route_archon(state: UnifiedState) -> str:
    stage = state.get("stage", "")
    if stage == "COMPLETE":
        return "polish"
    if stage == "RETHLAS":
        return "rethlas_agent"
    return "review_agent_node"


# ── 图 ────────────────────────────────────────────────────────────────


def build_unified_graph():
    """构建统一证明 StateGraph。
    
    改造后 (2026-05-20):
    search → rethlas_agent → verifier → (loop ≤3)
            ├── → autoformalize → planner → prover → reviewer → ...
            └── → rethlas_report → END
    """
    w = StateGraph(UnifiedState)
    # Rethlas 侧节点
    w.add_node("search", search_node)
    w.add_node("rethlas_agent", rethlas_agent_node)
    w.add_node("verifier", verifier_node)
    w.add_node("rethlas_report", failure_report_node)
    # Archon 侧节点
    w.add_node("autoformalize", autoformalize_node)
    w.add_node("planner", planner_node)
    w.add_node("prover", prover_node)
    w.add_node("reviewer", reviewer_node)
    w.add_node("polish", polish_node)
    w.add_node("review_agent_node", review_agent_node)
    
    w.set_entry_point("search")
    # Rethlas 自适应循环
    w.add_edge("search", "rethlas_agent")
    w.add_conditional_edges("rethlas_agent", route_rethlas_after_agent, {
        "verifier": "verifier",
        "autoformalize": "autoformalize",
        "rethlas_report": "rethlas_report",
    })
    w.add_conditional_edges("verifier", route_after_verify, {
        "rethlas_agent": "rethlas_agent",
        "autoformalize": "autoformalize",
        "rethlas_report": "rethlas_report",
    })
    w.add_edge("rethlas_report", END)
    # Archon 侧
    w.add_edge("autoformalize", "planner")
    w.add_edge("planner", "prover")
    w.add_edge("prover", "reviewer")
    w.add_conditional_edges("reviewer", route_archon, {
        "rethlas_agent": "rethlas_agent",
        "review_agent_node": "review_agent_node",
        "polish": "polish",
    })
    w.add_edge("polish", "review_agent_node")
    w.add_edge("review_agent_node", "planner")
    return w.compile(checkpointer=get_checkpointer())


def run_unified_workflow(statement: str, workspace_path: str = "", max_loops: int = 5,
                         parallel: bool = True, dry_run: bool = False) -> dict:
    return build_unified_graph().invoke(
        fresh_state(statement, workspace_path, max_loops, parallel=parallel, dry_run=dry_run),
        {"configurable": {"thread_id": "unified-proof"}},
    )
