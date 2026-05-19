"""
Archon DeerFlow — 增强版 Plan Agent
=====================================
节点：planner → prover (SubagentExecutor) → reviewer → review_agent
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
from langchain_core.messages import HumanMessage

from deerflow.subagents import SubagentConfig, SubagentExecutor
from deerflow.subagents.executor import (
    SubagentStatus,
    get_background_task_result,
    cleanup_background_task,
)

from .shared import (  # E1: 所有共享函数从 shared.py 导入
    classify_error, parse_lean_errors, format_errors,
    extract_goal, classify_failure,
    make_attempt, extract_code, extract_json,
    AUTO_TACTICS,
    sandbox_context, exec_with_sandbox,
    read_with_sandbox, write_with_sandbox,
    scan_sorries, count_sorries, build_project, verify_file,
    try_tactics_cascade, try_tactics_cascade_all,
    get_model_name, make_model,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# A1/E6: 状态 — TypedDict + Annotated reducers
# ═══════════════════════════════════════════════════════════════════════


def _merge_attempts(existing: list | None, new: list | None) -> list:
    """E6: attempt_history 的 reducer — 追加新条目。"""
    return (existing or []) + (new or [])


def _merge_failure_modes(existing: dict | None, new: dict | None) -> dict:
    """E6: failure_modes 的 reducer — 合并字典。"""
    merged = dict(existing or {})
    for k, v in (new or {}).items():
        merged[k] = merged.get(k, []) + v
    return merged


class ArchonState(TypedDict):
    messages: Annotated[list, add_messages]
    workspace_path: str
    stage: Literal["AUTOFORMALIZE", "PROVER", "POLISH", "COMPLETE"]
    pending: list[dict]
    completed: list[str]
    loop_count: int
    max_loops: int
    review: str
    # E6: Annotated reducer 保护
    attempt_history: Annotated[list, _merge_attempts]
    failure_modes: Annotated[dict, _merge_failure_modes]
    informal_hints: dict[str, str]
    previous_strategies: dict[str, list]
    user_hints: str
    thread_id: str


def fresh_state(ws: str, max_loops: int = 5, thread_id: str | None = None) -> ArchonState:
    return {
        "messages": [],
        "workspace_path": ws,
        "stage": "AUTOFORMALIZE",
        "pending": [],
        "completed": [],
        "loop_count": 0,
        "max_loops": max_loops,
        "review": "",
        "attempt_history": [],
        "failure_modes": {},
        "informal_hints": {},
        "previous_strategies": {},
        "user_hints": "",
        "thread_id": thread_id or f"archon-{Path(ws).name}",
    }


# ═══════════════════════════════════════════════════════════════════════
# Prompt 构建
# ═══════════════════════════════════════════════════════════════════════


_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills" / "custom"


def _build_system_prompt() -> str:
    """优先 apply_prompt_template，回退手动加载。"""
    try:
        from deerflow.agents.lead_agent.prompt import apply_prompt_template
        return apply_prompt_template(
            subagent_enabled=False,
            available_skills=set(["archon-lean4"]),
        )
    except Exception as e:
        logger.warning("[prompt] apply_prompt_template 失败: %s", e)
    skill_path = _SKILLS_DIR / "archon-lean4" / "SKILL.md"
    return skill_path.read_text() if skill_path.exists() else ""


# ═══════════════════════════════════════════════════════════════════════
# D1: Subagent 配置
# ═══════════════════════════════════════════════════════════════════════


PROVER_SUBAGENT_CONFIG = SubagentConfig(
    name="archon-prover",
    description="填充 Lean 文件中的 sorry 并编译验证",
    system_prompt=_build_system_prompt() or "你是 Lean4 形式化证明助手。\n\n"
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


# ═══════════════════════════════════════════════════════════════════════
# 节点：planner
# ═══════════════════════════════════════════════════════════════════════


def planner(state: ArchonState) -> ArchonState:
    """
    P1: Plan Agent — LLM 驱动的分析 + 目标设定。
    P2: 读取 USER_HINTS.md 注入上下文。
    P3: 扫描 .lean 文件中的 /- USER: ... -/ 注释。
    """
    ws = state["workspace_path"]
    loop = state.get("loop_count", 0) + 1
    logger.info("[plan] === loop #%d ===", loop)

    with sandbox_context(state.get("thread_id", "archon")) as sb:
        sorries = scan_sorries(ws, sb)
    logger.info("[plan] %d sorries found", len(sorries))

    if not sorries:
        return {**state, "stage": "COMPLETE", "loop_count": loop}

    # 分析 attempt_history → 失败模式
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
            logger.info("[plan] %s: 失败模式 %s", fn, modes)

    # P2: 读取 USER_HINTS.md
    user_hints = state.get("user_hints", "")
    hints_path = Path(ws) / ".archon-journal" / "USER_HINTS.md"
    if hints_path.exists():
        file_hints = hints_path.read_text().strip()
        if file_hints and not user_hints:
            user_hints = file_hints
            logger.info("[plan] 读取 USER_HINTS.md")

    # P3: 扫描 .lean 文件中的 /- USER: ... -/ 注释
    lean_user_comments = {}
    for s in sorries:
        fn = s["file"]
        content = Path(ws, fn).read_text() if Path(ws, fn).exists() else ""
        # 提取 /- USER: ... -/ 注释
        for m in re.finditer(r'/-\\s*USER:?(.*?)-/', content, re.DOTALL):
            comment = m.group(1).strip()
            line_before = content[:m.start()].count("\n") + 1
            lean_user_comments[fn] = f"[行 {line_before}] User 注释: {comment[:500]}"

    # P1: 调用 LLM 生成规划（当有失败历史或用户提示时）
    informal_hints = dict(state.get("informal_hints", {}))
    needs_llm = bool(user_hints) or bool(all_attempts)

    if needs_llm:
        # 构建 planner 提示
        plan_prompt_lines = [
            "你是 Archon Plan Agent。你的职责是分析当前证明状态并生成非形式化指引。",
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
            plan_prompt_lines.append(f"- {fn}:{s['line']}")
            if modes:
                plan_prompt_lines.append(f"  失败模式: {', '.join(modes)}")
            if strategies:
                plan_prompt_lines.append(f"  已尝试: {', '.join(strategies)}")
            if user_c:
                plan_prompt_lines.append(f"  {user_c}")

        if user_hints:
            plan_prompt_lines.extend(["", "## 用户提示", user_hints])

        plan_prompt_lines.extend([
            "",
            "## 输出要求",
            "对每个文件生成一段简短的非形式化证明指引（1-3 句）。",
            "格式：每行一个文件，用 | 分隔文件路径和指引。",
            "如果没有特殊指引，只输出空行。",
        ])

        try:
            resp = make_model().invoke([
                SystemMessage(content="你是 Archon Plan Agent。分析证明状态，提供指引。"),
                HumanMessage(content="\n".join(plan_prompt_lines)),
            ])
            plan_text = str(resp.content)

            for line in plan_text.split("\n"):
                if "|" in line:
                    parts = line.split("|", 1)
                    fn_candidate = parts[0].strip().rstrip(":")
                    hint = parts[1].strip()
                    if hint and len(hint) > 10:
                        # 去掉可能的前缀编号
                        clean_hint = re.sub(r'^\d+[.\\)\\s]*', '', hint)
                        if clean_hint:
                            informal_hints[fn_candidate] = clean_hint[:500]
                            logger.info("[plan] 指引 %s: %s", fn_candidate, clean_hint[:80])
        except Exception as e:
            logger.warning("[plan] LLM 规划失败: %s", e)

    return {
        **state,
        "loop_count": loop,
        "failure_modes": failure_modes,
        "previous_strategies": previous_strategies,
        "informal_hints": informal_hints,
        "pending": sorries,
        "user_hints": "",
        "stage": "PROVER",
    }


# ═══════════════════════════════════════════════════════════════════════
# 节点：prover
# ═══════════════════════════════════════════════════════════════════════


def _spawn_prove_subagent(executor: SubagentExecutor, t: dict, state: ArchonState) -> str | None:
    """为单个文件 spawn subagent。返回 task_id; None 表示已自动解决。
    P3: 读取 user_hints / USER 注释注入提示。
    """
    ws = state["workspace_path"]
    f = t["file"]
    line = t.get("line", "?")
    hints = state.get("informal_hints", {})
    failure_modes = state.get("failure_modes", {})

    with sandbox_context(state.get("thread_id", "archon")) as sb:
        content = read_with_sandbox(ws, f, sb)
        if not content or "sorry" not in content:
            return None
        cascade_ok, tactics_used = try_tactics_cascade_all(ws, f, sb)
        if cascade_ok:
            logger.info("[prove] %s 自动化策略: %s", f, tactics_used)
            return None
        goal_sig = extract_goal(
            content.split("\n"),
            int(line) if line.isdigit() else 0,
        ).get("signature", "")

        # P3: 提取文件中的 /- USER: ... -/ 注释（prover 读文件时也能看到，但提前放进提示）
        user_comments = []
        for m in re.finditer(r'/-\s*USER:?(.*?)-/', content, re.DOTALL):
            comment = m.group(1).strip()
            if comment:
                pos = content[:m.start()].count("\n") + 1
                user_comments.append(f"[行 {pos}] {comment[:300]}")

    hint = hints.get(f, "")
    fail_modes = failure_modes.get(f, [])
    goal_text = f"\n## 目标定理\n```lean\n{goal_sig}\n```" if goal_sig else ""
    hint_text = f"\n## 证明指引\n{hint}" if hint else ""
    user_text = ("\n## 文件内的用户提示\n" + "\n".join(user_comments)) if user_comments else ""
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

    task_msg = f"请处理 Lean 项目的文件 **{f}**（行 {line}）。{goal_text}{hint_text}{user_text}{fail_text}"
    task_id = f"prove-{Path(f).stem}"
    executor.execute_async(task_msg, task_id=task_id)
    return task_id


def _collect_subagent_result(task_id: str, t: dict, state: ArchonState,
                             max_wait: int = 660) -> None:
    """收集 subagent 结果并更新 state。"""
    ws = state["workspace_path"]
    f = t["file"]
    line = t.get("line", "?")
    loop_count = state["loop_count"]
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
                logger.info("[prove] subagent %s 完成", f)
            else:
                logger.warning("[prove] subagent %s 未完成", f)
            cleanup_background_task(task_id)
            return

        if result.status in (SubagentStatus.FAILED, SubagentStatus.TIMED_OUT):
            err = result.error or "unknown error"
            logger.warning("[prove] subagent %s %s: %s", f, result.status.value, err[:200])
            cleanup_background_task(task_id)
            return

        if result.status == SubagentStatus.CANCELLED:
            logger.warning("[prove] subagent %s 被取消", f)
            cleanup_background_task(task_id)
            return

        time.sleep(2)

    logger.warning("[prove] subagent %s 轮询超时 (%ds)", f, max_wait)


def prover(state: ArchonState) -> ArchonState:
    """D1: 使用 SubagentExecutor 为每个文件 spawn subagent。"""
    from deerflow.tools import get_available_tools

    ws = state["workspace_path"]
    pending = state.get("pending", [])
    thread_id = state.get("thread_id", "archon")

    if not pending:
        return state

    logger.info("[prove] 处理 %d 个文件 (SubagentExecutor)", len(pending))

    all_tools = get_available_tools(subagent_enabled=True)
    executor = SubagentExecutor(
        config=PROVER_SUBAGENT_CONFIG,
        tools=all_tools,
        thread_id=thread_id,
    )

    # 收集已完成的文件（自动化策略）
    completed = list(state.get("completed", []))
    new_attempts = list(state.get("attempt_history", []))
    task_ids = []

    for t in pending:
        f = t["file"]
        if not (Path(ws) / f).exists():
            continue
        tid = _spawn_prove_subagent(executor, t, state)
        if tid:
            task_ids.append((tid, t))

    for tid, t in task_ids:
        _collect_subagent_result(tid, t, state)

    # 重新读取 state 以获取被子函数修改的字段
    done = set(state.get("completed", [])) | set(completed)
    new_pending = [t for t in pending if t["file"] not in done]
    logger.info("[prove] 本轮: %d 完成, %d 剩余", len(done), len(new_pending))
    return {**state, "pending": new_pending}


# ═══════════════════════════════════════════════════════════════════════
# 节点：reviewer
# ═══════════════════════════════════════════════════════════════════════


def reviewer(state: ArchonState) -> ArchonState:
    """增强版 Reviewer — 纯逻辑节点。"""
    ws = state["workspace_path"]

    with sandbox_context(state.get("thread_id", "archon")) as sb:
        ok, log = build_project(ws, sb)
        n = count_sorries(ws, sb)

    done_count = len(state.get("completed", []))
    pending_count = len(state.get("pending", []))
    total_attempts = len(state.get("attempt_history", []))

    all_modes = {}
    for a in state.get("attempt_history", []):
        for m in a.get("failure_mode", "").split(","):
            m = m.strip()
            if m:
                all_modes[m] = all_modes.get(m, 0) + 1

    failure_summary = ""
    if all_modes:
        sorted_modes = sorted(all_modes.items(), key=lambda x: -x[1])
        failure_summary = " | ".join(f"{m}({c}次)" for m, c in sorted_modes)

    review = (
        f"Build: {'PASS' if ok else 'FAIL'}, "
        f"sorries: {n}, 已完成: {done_count}, "
        f"待处理: {pending_count}, 总尝试: {total_attempts}"
    )
    if failure_summary:
        review += f"\n失败模式分布: {failure_summary}"

    logger.info("[review] %s", review)
    stage = state["stage"]
    if ok and n == 0:
        stage = "COMPLETE"
    elif state["loop_count"] >= state["max_loops"]:
        stage = "COMPLETE"

    return {**state, "review": review, "stage": stage}


# ═══════════════════════════════════════════════════════════════════════
# 节点：review_agent
# ═══════════════════════════════════════════════════════════════════════


def review_agent(state: ArchonState) -> ArchonState:
    """审查代理：分析尝试历史，生成结构化工件。
    P2: 写入 USER_HINTS.md 文件供用户编辑。
    """
    ws = state["workspace_path"]
    if not Path(ws).exists():
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
    summary_lines = [f"# Session {loop} — 审查报告", "", f"时间: {now}", f"循环: #{loop}", "", "## 概览", ""]
    rec_lines = [f"# Session {loop} — 推荐", "", "## 优先级", ""]

    s_after = len(pending)
    summary_lines.append(f"- 本轮后 sorry: {s_after}")
    summary_lines.append(f"- 本轮完成: {len(completed)}")
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
            "missing_infrastructure": "换策略：尝试 induction/recursion",
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
        f"- 总 sorry: {s_after}", f"- 本轮解决: {len(completed)}",
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
        # 加入已知阻塞信息
        if blocked:
            hints_content.append("## 已知阻塞（不要重复尝试）")
            for fn in blocked:
                hints_content.append(f"- {fn}: {', '.join(failure_modes.get(fn, []))}")
            hints_content.append("")
        user_hints_path.write_text("\n".join(hints_content))

    logger.info("[review-agent] 期刊已写入 %s", session_dir)
    return state


# ═══════════════════════════════════════════════════════════════════════
# 路由 + 图
# ═══════════════════════════════════════════════════════════════════════


def route(state: ArchonState) -> str:
    return "review_agent" if state["stage"] != "COMPLETE" else END


def build_archon_graph():
    w = StateGraph(ArchonState)
    w.add_node("planner", planner)
    w.add_node("prover", prover)
    w.add_node("reviewer", reviewer)
    w.add_node("review_agent", review_agent)
    w.set_entry_point("planner")
    w.add_edge("planner", "prover")
    w.add_edge("prover", "reviewer")
    w.add_conditional_edges("reviewer", route, {"review_agent": "review_agent", END: END})
    w.add_edge("review_agent", "planner")
    return w.compile()


def run_archon_workflow(ws: str, max_loops: int = 5) -> dict:
    return build_archon_graph().invoke(
        fresh_state(ws, max_loops),
        {"configurable": {"thread_id": f"archon-{Path(ws).name}"}},
    )
