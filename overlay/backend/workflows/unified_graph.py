"""
Unified Math Prover — Rethlas 非形式化证明 + Archon Lean4 形式化
================================================================
组合架构:

用户输入命题
    │
    ▼
rethlas_generate ──→ rethlas_verify
    ▲                      │
    └── wrong (≤2 retries) │
                           ▼ correct
                    archon_planner
                           │
                           ▼
                    archon_prover
                           │
                           ▼
                    archon_reviewer ──→ COMPLETE
"""

import json, os, re, subprocess
from pathlib import Path
from typing import Annotated, Literal

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.models import create_chat_model

# ── 搜索端点 ──────────────────────────────────────────────────────────
SEARCH_URL = "https://leansearch.net/thm/search"

# ── 状态 ──────────────────────────────────────────────────────────────


class UnifiedState(dict):
    messages: Annotated[list, add_messages]

    # Rethlas 阶段
    statement: str              # 用户输入的数学命题
    informal_proof: str         # 生成的<proof>非形式化证明
    rethlas_attempts: int       # 生成尝试次数
    rethlas_history: list       # 修复历史
    rethlas_failed: bool        # 3 次仍未通过

    # Archon 阶段
    workspace_path: str
    stage: Literal["AUTOFORMALIZE", "PROVER", "POLISH", "COMPLETE"]
    pending: list
    completed: list
    loop_count: int
    max_loops: int
    review: str


def fresh_state(statement: str, ws: str = "", max_loops: int = 5) -> UnifiedState:
    return UnifiedState(
        messages=[],
        statement=statement,
        informal_proof="",
        rethlas_attempts=0,
        rethlas_history=[],
        rethlas_failed=False,
        workspace_path=ws,
        stage="AUTOFORMALIZE",
        pending=[], completed=[], loop_count=0,
        max_loops=max_loops, review="",
    )


# ── 工具 ──────────────────────────────────────────────────────────────


def _bash(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    PATH = f"{os.path.expanduser('~/.elan/bin')}:{os.environ.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True,
        timeout=300, env={**os.environ, "PATH": PATH},
    )


def _model(name="deepseek-v4", think=False):
    return create_chat_model(name, thinking_enabled=think)


def _search_theorems(query: str) -> list[dict]:
    """通过 leansearch.net 搜索相关定理"""
    import urllib.request, ssl

    payload = json.dumps({
        "query": query,
        "task": "Given a math statement, retrieve useful references.",
        "num_results": 5,
    }).encode()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            SEARCH_URL, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[search] 搜索失败: {e}")
        return []


def _extract_proof(text: str) -> str:
    """从 LLM 回复中提取 <proof> 内容"""
    m = re.search(r'<proof>(.*?)</proof>', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _extract_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON"""
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"verdict": "parse_failed"}


def _scan(ws: str) -> list[dict]:
    r = _bash("grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/'", ws)
    items = []
    for line in r.stdout.strip().split("\n"):
        p = line.split(":", 2)
        if len(p) >= 2:
            items.append({"file": p[0], "line": p[1]})
    return items


def _sorries(ws: str) -> int:
    r = _bash("grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/' | wc -l", ws)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def _build(ws: str) -> tuple[bool, str]:
    r = _bash("lake build 2>&1", ws)
    return r.returncode == 0, r.stdout + r.stderr


def _read(ws: str, f: str) -> str:
    p = Path(ws) / f
    return p.read_text() if p.exists() else ""


def _write(ws: str, f: str, content: str) -> None:
    (Path(ws) / f).write_text(content)


def _extract(text: str) -> str:
    m = re.search(r'```(?:lean)?\s*\n?(.*?)```', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


# ══════════════════════════════════════════════════════════════════
# Rethlas 节点
# ══════════════════════════════════════════════════════════════════


def search_node(state: UnifiedState) -> UnifiedState:
    """Step 0: 搜索相关定理作为上下文注入"""
    stmt = state["statement"]
    print(f"[search] 搜索: {stmt[:60]}...")

    results = _search_theorems(stmt)
    if results:
        context_lines = []
        for r in results[:3]:
            title = r.get("title", "")
            theorem = r.get("theorem", "")
            if title or theorem:
                context_lines.append(f"- {title}: {theorem[:200]}")
        if context_lines:
            context = "\n".join(context_lines)
            print(f"[search] 找到 {len(results)} 条结果")
            # 注入到 state 供后续节点使用
            state["messages"].append(
                SystemMessage(content=f"[CONTEXT] 相关定理:\n{context}")
            )
        else:
            print(f"[search] 无结构化结果")
    else:
        print(f"[search] 无结果")
    return state


def generator_node(state: UnifiedState) -> UnifiedState:
    """Step 1: 生成非形式化证明"""
    state["rethlas_attempts"] += 1
    stmt = state["statement"]
    attempt = state["rethlas_attempts"]

    # 加载 generator 提示词
    gen_prompt_path = Path("/home/zdzdhd/deer-flow/skills/custom/math-prover/prompts/generator.md")
    gen_prompt = gen_prompt_path.read_text() if gen_prompt_path.exists() else ""

    # 构建消息
    messages = [SystemMessage(content=gen_prompt)]

    # 如果有修复历史，添加上下文
    if state.get("rethlas_history"):
        last = state["rethlas_history"][-1]
        messages.append(SystemMessage(content=(
            f"之前生成的证明被驳回。审核反馈:\n"
            f"{json.dumps(last, indent=2, ensure_ascii=False)}\n\n"
            f"请根据审稿人的反馈修改证明。在重新生成前，复述一遍原始定理和所有假设。"
        )))

    messages.append(HumanMessage(content=f"请证明: {stmt}"))
    print(f"[rethlas] generate attempt {attempt}")

    resp = _model().invoke(messages)
    proof = _extract_proof(str(resp.content))
    state["informal_proof"] = proof

    print(f"[rethlas] proof generated ({len(proof)} chars)")
    return state


def verifier_node(state: UnifiedState) -> UnifiedState:
    """Step 2: 验证非形式化证明"""
    stmt = state["statement"]
    proof = state["informal_proof"]

    ver_path = Path("/home/zdzdhd/deer-flow/skills/custom/math-prover/prompts/verifier.md")
    ver_prompt = ver_path.read_text() if ver_path.exists() else ""

    resp = _model(think=False).invoke([
        SystemMessage(content=ver_prompt),
        HumanMessage(content=f"Statement: {stmt}\n\nProof:\n{proof}"),
    ])

    verdict = _extract_json(str(resp.content))
    print(f"[rethlas] verify: {verdict.get('verdict', '?')}")

    # 记录历史
    state["rethlas_history"].append({
        "attempt": state["rethlas_attempts"],
        "verdict": verdict,
    })

    if verdict.get("verdict") != "correct":
        if state["rethlas_attempts"] >= 3:
            state["rethlas_failed"] = True
            print(f"[rethlas] ❌ 3 次尝试均失败")
        else:
            print(f"[rethlas] 🔄 修复重试 ({state['rethlas_attempts']}/3)")
    else:
        print(f"[rethlas] ✅ 证明通过验证")

    return state


def route_rethlas(state: UnifiedState) -> str:
    """Rethlas 循环路由"""
    if state.get("rethlas_failed"):
        return "rethlas_report"
    if state.get("rethlas_attempts", 0) >= 3:
        return "rethlas_report"
    # 检查最后一次验证结果
    history = state.get("rethlas_history", [])
    if history and history[-1].get("verdict", {}).get("verdict") == "correct":
        return "planner"
    return "generator"


def failure_report_node(state: UnifiedState) -> UnifiedState:
    """Step 3: 输出失败报告"""
    stmt = state["statement"]
    history = state.get("rethlas_history", [])
    last = history[-1] if history else {}
    last_verdict = last.get("verdict", {})
    last_proof = state.get("informal_proof", "")

    report = (
        f"## 证明失败报告\n\n"
        f"**命题：** {stmt}\n\n"
        f"**尝试次数：** {len(history)}\n\n"
        f"**最后一次草稿：**\n```\n{last_proof[:1000]}\n```\n\n"
        f"**最后一次验证反馈：**\n"
        f"```json\n{json.dumps(last_verdict, indent=2, ensure_ascii=False)}\n```\n\n"
        f"**失败原因总结：**\n"
    )
    errors = last_verdict.get("verification_report", {}).get("critical_errors", [])
    gaps = last_verdict.get("verification_report", {}).get("gaps", [])
    for e in errors:
        report += f"- critical: {e.get('issue', '?')}\n"
    for g in gaps:
        report += f"- gap: {g.get('issue', '?')}\n"

    state["review"] = report
    state["stage"] = "COMPLETE"
    print(f"[rethlas] 失败报告已生成")
    return state


# ══════════════════════════════════════════════════════════════════
# Archon 节点（复用简化版）
# ══════════════════════════════════════════════════════════════════


def planner_node(state: UnifiedState) -> UnifiedState:
    ws = state["workspace_path"]
    state["loop_count"] += 1

    if not ws or not Path(ws).exists():
        print("[archon] 未提供工作区路径，跳过形式化")
        state["stage"] = "COMPLETE"
        return state

    sorries = _scan(ws)
    print(f"[archon] plan: {len(sorries)} sorries")
    state["pending"] = sorries

    if not sorries:
        state["stage"] = "COMPLETE"
    else:
        state["stage"] = "PROVER"
    return state


def prover_node(state: UnifiedState) -> UnifiedState:
    ws = state["workspace_path"]
    if not ws:
        return state

    pending = state.get("pending", [])
    informal = state.get("informal_proof", "")
    done = []

    for t in pending:
        f = t["file"]
        path = Path(ws) / f
        if not path.exists() or "sorry" not in path.read_text():
            done.append(f)
            continue

        print(f"[archon] prove: {f}")
        file_content = path.read_text()

        # 注入非形式化证明作为上下文
        system_msg = "Fill every `sorry` with a correct Lean 4 proof."
        if informal:
            system_msg += f"\n\n非形式化证明参考:\n{informal}"

        resp = _model().invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=f"File {f}:\n```lean\n{file_content}\n```"),
        ])
        code = _extract(str(resp.content))
        if code and "sorry" not in code:
            _write(ws, f, code)
            ok, _ = _build(ws)
            if ok:
                print(f"[archon] ✅ {f}")
                done.append(f)
                continue

        # 卡住→推理模型
        hint = _model(think=True).invoke([
            SystemMessage(content="Provide an informal proof sketch."),
            HumanMessage(content=f"Prove in Lean:\n{file_content}"),
        ])
        resp2 = _model().invoke([
            SystemMessage(content=f"Use hint to fill the sorry.\nHint: {hint.content}"),
            HumanMessage(content=f"```lean\n{_read(ws, f)}\n```"),
        ])
        code2 = _extract(str(resp2.content))
        if code2 and "sorry" not in code2:
            _write(ws, f, code2)
            ok, _ = _build(ws)
            if ok:
                done.append(f)

    state["completed"].extend(done)
    state["pending"] = [t for t in pending if t["file"] not in done]
    return state


def reviewer_node(state: UnifiedState) -> UnifiedState:
    ws = state["workspace_path"]
    if not ws:
        state["stage"] = "COMPLETE"
        return state

    ok, log = _build(ws)
    n = _sorries(ws)
    r = f"Build: {'PASS' if ok else 'FAIL'}, sorries: {n}"
    state["review"] = r
    print(f"[archon] review: {r}")

    if ok and n == 0:
        state["stage"] = "COMPLETE"
    elif state["loop_count"] >= state["max_loops"]:
        state["stage"] = "COMPLETE"
    return state


def route_archon(state: UnifiedState) -> str:
    return END if state["stage"] == "COMPLETE" else "planner"


# ══════════════════════════════════════════════════════════════════
# 构建统一图
# ══════════════════════════════════════════════════════════════════


def build_unified_graph():
    """构建 Rethlas + Archon 统一工作流"""
    w = StateGraph(UnifiedState)

    # Rethlas 节点
    w.add_node("search", search_node)
    w.add_node("generator", generator_node)
    w.add_node("verifier", verifier_node)
    w.add_node("rethlas_report", failure_report_node)

    # Archon 节点
    w.add_node("planner", planner_node)
    w.add_node("prover", prover_node)
    w.add_node("reviewer", reviewer_node)

    # 入口
    w.set_entry_point("search")

    # Rethlas 循环边
    w.add_edge("search", "generator")
    w.add_edge("generator", "verifier")
    w.add_conditional_edges("verifier", route_rethlas, {
        "generator": "generator",
        "planner": "planner",
        "rethlas_report": "rethlas_report",
    })

    # Archon 边
    w.add_edge("rethlas_report", END)
    w.add_edge("planner", "prover")
    w.add_edge("prover", "reviewer")
    w.add_conditional_edges("reviewer", route_archon)

    return w.compile()


def run_unified_workflow(statement: str, workspace_path: str = "",
                         max_loops: int = 5) -> dict:
    """运行完整统一工作流"""
    return build_unified_graph().invoke(
        fresh_state(statement, workspace_path, max_loops),
        {"configurable": {"thread_id": "unified-proof"}},
    )
