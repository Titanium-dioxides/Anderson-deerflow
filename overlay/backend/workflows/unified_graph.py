"""
Unified Math Prover — Rethlas 非形式化证明 → Archon(Lean) 验证
================================================================
Rethlas: generate → verify → repair(≤3) → Archon: planner → prover → reviewer
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
)

logger = logging.getLogger(__name__)


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
    attempt_history: Annotated[list, _merge_attempts]
    failure_modes: Annotated[dict, _merge_failure_modes]
    informal_hints: dict[str, str]
    previous_strategies: dict[str, list]


def fresh_state(statement: str, ws: str = "", max_loops: int = 5) -> UnifiedState:
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
        "attempt_history": [],
        "failure_modes": {},
        "informal_hints": {},
        "previous_strategies": {},
    }


# ── 工具函数 ────────────────────────────────────────────────────────────


def _read_prompt(path: str) -> str:
    p = Path(path)
    return p.read_text() if p.exists() else ""


def _extract_proof(text: str) -> str:
    m = re.search(r'<proof>(.*?)</proof>', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


# ── Rethlas 节点 ───────────────────────────────────────────────────────


def search_node(state: UnifiedState) -> UnifiedState:
    state = dict(state)
    statement = state["statement"]
    logger.info("[search] 搜索相关定理: %s", statement[:80])
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
    except Exception as e:
        logger.warning("[search] 远程搜索失败: %s", e)
        results = []

    search_context = ""
    if results:
        lines = ["## 相关定理"]
        for r in results[:5]:
            thm = r.get("theorem", "") or r.get("title", "")
            if thm and len(thm) < 500:
                lines.append(f"- {thm}")
        search_context = "\n".join(lines)

    state["messages"].append(HumanMessage(
        content=f"用户命题: {statement}\n\n{search_context}\n\n请根据搜索结果生成证明。"
    ))
    return state


def generator_node(state: UnifiedState) -> UnifiedState:
    state = dict(state)
    statement = state["statement"]
    rethlas_attempts = state.get("rethlas_attempts", 0)
    archon_feedback = state.get("archon_feedback", "")

    gen_prompt = _read_prompt(_GEN_PROMPT)
    feedback = f"\n\n## 上次 Lean 编译错误（需修复证明中的错误）\n{archon_feedback}" if archon_feedback else ""

    resp = make_model().invoke([
        SystemMessage(content=gen_prompt),
        HumanMessage(content=f"## 命题\n{statement}\n{feedback}\n\n请生成证明。"),
    ])
    proof = _extract_proof(str(resp.content))
    logger.info("[generate] 生成了 %d 字符证明", len(proof))

    state["informal_proof"] = proof
    state["rethlas_attempts"] = rethlas_attempts + 1
    state["archon_feedback"] = ""
    return state


def verifier_node(state: UnifiedState) -> UnifiedState:
    state = dict(state)
    proof = state.get("informal_proof", "")

    ver_prompt = _read_prompt(_VER_PROMPT)
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
    """PR2: autoformalize 阶段 — 将 Rethlas 非形式化证明转为 Lean 声明骨架。"""
    state = dict(state)
    ws = state["workspace_path"]
    proof = state.get("informal_proof", "")
    statement = state["statement"]

    if not ws:
        logger.info("[autoformalize] 无项目路径，跳过")
        return {**state, "stage": "AUTOFORMALIZE"}

    project_path = Path(ws)
    if not project_path.exists():
        logger.info("[autoformalize] 项目目录不存在，创建: %s", ws)
        project_path.mkdir(parents=True, exist_ok=True)

    # 检查是否已有 .lean 文件
    lean_files = list(project_path.glob("*.lean")) + list(project_path.glob("**/*.lean"))
    lean_files = [f for f in lean_files if '.lake' not in str(f)]

    if lean_files:
        logger.info("[autoformalize] 已有 %d 个 .lean 文件，跳过 autoformalize", len(lean_files))
        return {**state, "stage": "AUTOFORMALIZE"}

    if not proof:
        logger.warning("[autoformalize] 无非形式化证明，跳过")
        return {**state, "stage": "AUTOFORMALIZE"}

    # 调用 LLM 生成 Lean 声明骨架
    prompt = (
        f"你是一个 Lean4 形式化专家。请将以下数学命题和证明翻译为 Lean 4 代码。\n"
        f"输出格式：一个完整的 .lean 文件内容，包含正确的 imports 和声明。\n"
        f"对于需要证明但尚未完成的部分，使用 `:= by\n  sorry` 占位。\n"
        f"重点：确保类型签名准确，声明结构与 Mathlib 风格一致。\n"
        f"\n## 命题\n{statement}\n"
        f"\n## 非形式化证明\n{proof[:8000]}\n"
    )

    try:
        resp = make_model().invoke([
            SystemMessage(content="你是 Lean4 形式化专家。将数学命题翻译为 Lean 声明骨架。"),
            HumanMessage(content=prompt),
        ])
        code = extract_code(str(resp.content))
        if code:
            # 写入主文件
            main_file = project_path / "Main.lean"
            main_file.write_text(code)
            logger.info("[autoformalize] 写入 %s (%d 字符)", main_file, len(code))

            # 尝试创建 lakefile 如果不存在
            lakefile = project_path / "lakefile.toml"
            if not lakefile.exists():
                lakefile_text = (
                    '[package]\n'
                    'name = "' + project_path.name + '"\n'
                    'version = "0.1.0"\n'
                    '\n'
                    '[dependencies]\n'
                    'mathlib = { git = "https://github.com/leanprover-community/mathlib4.git" }\n'
                )
                lakefile.write_text(lakefile_text)
                logger.info("[autoformalize] 创建 %s", lakefile)
    except Exception as e:
        logger.exception("[autoformalize] LLM 生成失败: %s", e)

    return {**state, "stage": "AUTOFORMALIZE"}


# ── PR3: Polish 节点 ───────────────────────────────────────────────────


def polish_node(state: UnifiedState) -> UnifiedState:
    """PR3: Polish 阶段 — 最终检查、清理、refactor。"""
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


UNIFIED_PROVER_CONFIG = SubagentConfig(
    name="unified-prover",
    description="填充 Lean 文件中的 sorry 并编译验证",
    system_prompt="你是 Lean4 形式化证明助手。\n\n"
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

    if not pending:
        return state

    logger.info("[prove-node] 处理 %d 个文件 (SubagentExecutor)", len(pending))

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
            task_ids.append((tid, t))

    for tid, t in task_ids:
        _collect_prove_result(tid, t, state)

    done = set(state.get("completed", [])) | set(completed)
    new_pending = [t for t in pending if t["file"] not in done]
    logger.info("[prove-node] 本轮: %d 完成, %d 剩余", len(done), len(new_pending))
    return {**state, "pending": new_pending}


def reviewer_node(state: UnifiedState) -> UnifiedState:
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
    if ok and n == 0:
        stage = "COMPLETE"
    elif state["loop_count"] >= state["max_loops"]:
        stage = "COMPLETE"

    archon_feedback = state.get("archon_feedback", "")
    if not ok and n > 0:
        archon_feedback = log[-2000:] if len(log) > 2000 else log
        stage = "RETHLAS"

    return {**state, "review": review, "stage": stage, "archon_feedback": archon_feedback}


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


def route_rethlas(state: UnifiedState) -> str:
    stage = state.get("stage", "")
    if stage == "AUTOFORMALIZE":
        return "autoformalize"
    if stage == "RETHLAS" or state.get("rethlas_failed"):
        return "rethlas_report" if state.get("rethlas_failed") else "generator"
    return "generator"


def route_archon(state: UnifiedState) -> str:
    stage = state.get("stage", "")
    if stage == "COMPLETE":
        return "polish"
    if stage == "RETHLAS":
        return "generator"
    return "review_agent_node"


# ── 图 ────────────────────────────────────────────────────────────────


def build_unified_graph():
    w = StateGraph(UnifiedState)
    w.add_node("search", search_node)
    w.add_node("generator", generator_node)
    w.add_node("verifier", verifier_node)
    w.add_node("rethlas_report", failure_report_node)
    w.add_node("autoformalize", autoformalize_node)
    w.add_node("planner", planner_node)
    w.add_node("prover", prover_node)
    w.add_node("reviewer", reviewer_node)
    w.add_node("polish", polish_node)
    w.add_node("review_agent_node", review_agent_node)
    w.set_entry_point("search")
    w.add_edge("search", "generator")
    w.add_edge("generator", "verifier")
    w.add_conditional_edges("verifier", route_rethlas, {
        "generator": "generator", "autoformalize": "autoformalize", "rethlas_report": "rethlas_report",
    })
    w.add_edge("rethlas_report", END)
    w.add_edge("autoformalize", "planner")
    w.add_edge("planner", "prover")
    w.add_edge("prover", "reviewer")
    w.add_conditional_edges("reviewer", route_archon, {
        "generator": "generator", "review_agent_node": "review_agent_node", "polish": "polish",
    })
    w.add_edge("polish", "review_agent_node")
    w.add_edge("review_agent_node", "planner")
    return w.compile()


def run_unified_workflow(statement: str, workspace_path: str = "", max_loops: int = 5) -> dict:
    return build_unified_graph().invoke(
        fresh_state(statement, workspace_path, max_loops),
        {"configurable": {"thread_id": "unified-proof"}},
    )
