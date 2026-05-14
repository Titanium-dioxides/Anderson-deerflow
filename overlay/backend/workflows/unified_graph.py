"""
Unified Math Prover — Rethlas 非形式化证明 → Archon(Lean) 验证
================================================================
完整保留两端原始 Agent 工作流：

  Rethlas: generate → verify(JSON) → repair(≤3)
  Archon:  planner → prover → reviewer

  用户命题
      │
      ▼
  ┌─ Rethlas Generate ────────┐
  │  (prompts/generator.md)    │
  └─────────┬──────────────────┘
            │ <proof>...
            ▼
  ┌─ Rethlas Verify ──────────┐
  │  (prompts/verifier.md)    │  JSON self-check
  │  verdict=="wrong" → fix   │  ≤3 rounds
  └─────────┬──────────────────┘
            │ correct
            ▼
  ┌─ Archon Planner ──────────┐
  │  扫描 sorry, 排优先级     │
  └─────────┬──────────────────┘
            │
            ▼
  ┌─ Archon Prover ───────────┐
  │  以 Rethlas proof 为指引  │
  │  填充 Lean 代码           │
  └─────────┬──────────────────┘
            │
            ▼
  ┌─ Archon Reviewer ─────────┐
  │  lake build 验证          │
  │                            │
  ├── PASS → COMPLETE ✅      │
  │                            │
  └── FAIL → Rethlas(Lean err)┘
              ▲ (Rethlas 阅读理解 Lean 错误, 修复证明)
              │
              └── 重新生成 ───┘
"""

import datetime
import json, os, re, subprocess
from pathlib import Path
from typing import Annotated, Literal

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.models import create_chat_model


# ── 路径常量 ──────────────────────────────────────────────────────────
_PROJECT_DIR = Path(__file__).parent.parent.parent
_RETHLAS_DIR = _PROJECT_DIR / "skills" / "custom" / "math-prover"
_GEN_PROMPT = str(_RETHLAS_DIR / "prompts" / "generator.md")
_VER_PROMPT = str(_RETHLAS_DIR / "prompts" / "verifier.md")
_SEARCH_URL = "https://leansearch.net/thm/search"

# ── 状态 ──────────────────────────────────────────────────────────────


class UnifiedState(dict):
    messages: Annotated[list, add_messages]

    # 命题
    statement: str                    # 用户输入的数学命题

    # Rethlas 阶段 (保留原 Rethlas Agent 工作流)
    informal_proof: str               # 生成的 <proof>...
    rethlas_attempts: int             # 生成→验证轮数
    rethlas_history: list             # 修复历史 [{attempt, verdict, ...}]
    rethlas_failed: bool              # 3 轮均未通过

    # Archon 阶段 (保留原 Archon Agent 工作流)
    workspace_path: str
    stage: Literal["AUTOFORMALIZE", "PROVER", "POLISH", "COMPLETE"]
    pending: list
    completed: list
    loop_count: int
    max_loops: int
    review: str

    # 跨层反馈
    archon_feedback: str              # Lean 编译错误 → 送回 Rethlas
    archon_outer_cycles: int           # Rethlas→Archon 外层尝试次数

    # 增强 Archon Plan Agent 字段
    attempt_history: list[dict]        # [{file, line, strategy, result, lean_error, failure_mode, loop}, ...]
    failure_modes: dict[str, list]    # {file: [failure_mode, ...]}
    informal_hints: dict[str, str]    # {file: "非形式化证明指引"}
    previous_strategies: dict[str, list]  # {file: ["策略已尝试列表"]}


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
        archon_feedback="",
        archon_outer_cycles=0,
        attempt_history=[], failure_modes={},
        informal_hints={}, previous_strategies={},
    )


# ── 基础工具 ──────────────────────────────────────────────────────────


def _bash(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    PATH = f"{os.path.expanduser('~/.elan/bin')}:{os.environ.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True,
        timeout=300, env={**os.environ, "PATH": PATH},
    )


def _model(name="deepseek-v4", think=False):
    return create_chat_model(name, thinking_enabled=think)


def _read_prompt(path: str) -> str:
    p = Path(path)
    return p.read_text() if p.exists() else ""


def _extract_proof(text: str) -> str:
    m = re.search(r'<proof>(.*?)</proof>', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _extract_json(text: str) -> dict:
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"verdict": "parse_failed"}


def _extract_code(text: str) -> str:
    m = re.search(r'```(?:lean)?\s*\n?(.*?)```', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _scan(ws: str) -> list[dict]:
    r = _bash("grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/'", ws)
    items = []
    for line in r.stdout.strip().split("\n"):
        parts = line.split(":", 2)
        if len(parts) >= 2:
            items.append({"file": parts[0], "line": parts[1]})
    return items


def _sorries(ws: str) -> int:
    r = _bash("grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/' | wc -l", ws)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def _build(ws: str) -> tuple[bool, str]:
    r = _bash("lake build 2>&1", ws)
    return r.returncode == 0, r.stderr + r.stdout


def _read(ws: str, f: str) -> str:
    p = Path(ws) / f
    return p.read_text() if p.exists() else ""


def _write(ws: str, f: str, content: str) -> None:
    p = Path(ws) / f
    p.write_text(content)


# ═══════════════════════════════════════════════════════════════════════
# Phase 1：增量编译 + 结构化错误解析（与 archon_graph.py 同步）
# ═══════════════════════════════════════════════════════════════════════


def _classify_error(msg: str) -> str:
    m = msg.lower()
    if "type mismatch" in m:
        return "type_mismatch"
    if any(kw in m for kw in ["unknown identifier", "unknown constant", "unknown declaration",
                               "unknown theorem", "unknown lemma", "unknown definition"]):
        return "unknown_identifier"
    if "failed to synthesize" in m:
        return "failed_to_synthesize"
    if "don't know how to" in m:
        return "don_know_how"
    if "invalid" in m:
        return "invalid"
    if any(kw in m for kw in ["expected", "unexpected"]):
        return "syntax_error"
    if "ambiguous" in m:
        return "ambiguous"
    if "is not a" in m or "has type" in m:
        return "type_error"
    return "other"


def _parse_lean_errors(stderr: str) -> list[dict]:
    errors = []
    current = None
    for line in stderr.split("\n"):
        m = re.match(r'^(.+?):(\d+):(\d+):\s*(error|warning):\s*(.*)$', line)
        if m:
            if current:
                errors.append(current)
            current = {
                "type": _classify_error(m.group(5)),
                "severity": m.group(4),
                "file": m.group(1),
                "line": int(m.group(2)),
                "col": int(m.group(3)),
                "message": m.group(5).strip(),
                "raw": line,
            }
        elif current:
            current["message"] = current["message"].rstrip("\n") + "\n" + line
    if current:
        errors.append(current)
    return errors


def _verify_file(ws: str, f: str) -> tuple[bool, list[dict]]:
    """Per-file incremental verification via `lake env lean` (~1-2s)."""
    r = _bash(f"lake env lean {f} 2>&1", ws)
    if r.returncode == 0:
        return (True, [])
    return (False, _parse_lean_errors(r.stderr if r.stderr else r.stdout))


def _format_errors(errors: list[dict], max_lines: int = 40) -> str:
    lines = []
    for e in errors[:5]:
        lines.append(f"{e['type']} at {e['file']}:{e['line']}:{e['col']}")
        for l in e['message'].split("\n")[:8]:
            lines.append(f"  {l}")
        lines.append("")
    combined = "\n".join(lines)
    if len(combined) > max_lines * 80:
        combined = combined[:max_lines * 80] + "\n... (truncated)"
    return combined


def _search(query: str) -> list[dict]:
    import urllib.request, ssl
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            _SEARCH_URL,
            data=json.dumps({"query": query, "task": "retrieve useful theorems", "num_results": 5}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            return json.loads(resp.read().decode()) if resp else []
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════
# Rethlas 节点 (保留原始 Agent 工作流: generate → verify JSON → repair)
# ═══════════════════════════════════════════════════════════════════════


def search_node(state: UnifiedState) -> UnifiedState:
    """Step 0: 外部定理检索（可选）"""
    results = _search(state["statement"])
    if results:
        ctx = "\n".join(
            f"- {r.get('title','')}: {r.get('theorem','')[:200]}"
            for r in results[:3] if r.get('theorem')
        )
        if ctx:
            state["messages"].append(SystemMessage(content=f"[CONTEXT] 相关定理:\n{ctx}"))
            print(f"[search] 检索到 {len(results)} 条结果")
    return state


def generator_node(state: UnifiedState) -> UnifiedState:
    """Step 1: Rethlas 非形式化证明生成 (原始 generator.md)"""
    state["rethlas_attempts"] += 1
    stmt = state["statement"]
    attempt = state["rethlas_attempts"]

    gen_prompt = _read_prompt(_GEN_PROMPT)
    sys_msg = gen_prompt

    # 如果有 Archon 反馈的 Lean 错误 → Rethlas 阅读理解
    if state.get("archon_feedback"):
        sys_msg += (
            f"\n\n之前的形式化验证失败，Lean 编译错误如下:\n"
            f"{state['archon_feedback'][-3000:]}"
            f"\n\n请阅读这些错误，理解为什么你的非形式化证明在形式化时出了问题，"
            f"然后修复证明。"
        )
        print(f"[rethlas] 正在阅读理解 Lean 错误并修复证明 (outer#{state['archon_outer_cycles']})")

    # 如果有修复历史
    if state.get("rethlas_history"):
        last = state["rethlas_history"][-1]
        sys_msg += (
            f"\n\n之前的审核反馈:\n{json.dumps(last.get('verdict',{}), indent=2, ensure_ascii=False)}"
        )

    resp = _model().invoke([
        SystemMessage(content=sys_msg),
        HumanMessage(content=f"请证明: {stmt}"),
    ])
    proof = _extract_proof(str(resp.content))
    state["informal_proof"] = proof
    print(f"[rethlas] generate attempt {attempt} ({len(proof)} chars)")
    if state.get("archon_feedback"):
        state["archon_feedback"] = ""  # 清除反馈，避免重复
    return state


def verifier_node(state: UnifiedState) -> UnifiedState:
    """Step 2: Rethlas 自我验证 (原始 verifier.md, 输出 JSON verdict)"""
    stmt = state["statement"]
    proof = state["informal_proof"]
    ver_prompt = _read_prompt(_VER_PROMPT)

    resp = _model(think=False).invoke([
        SystemMessage(content=ver_prompt),
        HumanMessage(content=f"Statement:\n{stmt}\n\nProof:\n{proof}"),
    ])
    verdict = _extract_json(str(resp.content))
    state["rethlas_history"].append({
        "attempt": state["rethlas_attempts"],
        "verdict": verdict,
    })

    v = verdict.get("verdict", "?")
    print(f"[rethlas] verify: {v}")

    if v == "correct":
        print(f"[rethlas] ✅ 非形式化证明通过自我验证")
    elif state["rethlas_attempts"] >= 3:
        state["rethlas_failed"] = True
        print(f"[rethlas] ❌ 3 轮自我验证均未通过")
    else:
        print(f"[rethlas] 🔄 修复 (attempt {state['rethlas_attempts']}/3)")

    return state


def route_rethlas(state: UnifiedState) -> str:
    """Rethlas 循环路由"""
    if state.get("rethlas_failed"):
        return "rethlas_report"
    if state["rethlas_attempts"] >= 3:
        return "rethlas_report"
    history = state.get("rethlas_history", [])
    if history and history[-1].get("verdict", {}).get("verdict") == "correct":
        return "planner"
    return "generator"


def failure_report_node(state: UnifiedState) -> UnifiedState:
    """Rethlas 自我验证失败报告"""
    stmt = state["statement"]
    hist = state.get("rethlas_history", [])
    last_v = hist[-1]["verdict"] if hist else {}
    report = (
        f"## 非形式化证明失败报告\n\n"
        f"**命题：** {stmt}\n\n"
        f"**尝试次数：** {len(hist)}\n\n"
        f"**最后一次验证反馈：**\n"
        f"```json\n{json.dumps(last_v, indent=2, ensure_ascii=False)}\n```"
    )
    state["review"] = report
    state["stage"] = "COMPLETE"
    print(f"[rethlas] 失败报告已生成")
    return state


# ═══════════════════════════════════════════════════════════════════════
# Archon 节点 (保留原始 Agent 工作流: planner → prover → reviewer)
# ═══════════════════════════════════════════════════════════════════════


def _classify_failure(attempt: dict) -> list[str]:
    """Return list of failure modes from an attempt record."""
    err = attempt.get("lean_error", "").lower()
    modes = []
    keywords = {
        "missing_infrastructure": ["unknown identifier", "unknown constant", "unknown declaration",
                                    "unknown theorem", "unknown lemma", "not found in"],
        "typeclass": ["failed to synthesize", "typeclass", "instance", "no instances"],
        "wrong_construction": ["type mismatch", "expected", "don't know how to", "has type"],
    }
    for mode, kws in keywords.items():
        if any(kw in err for kw in kws):
            modes.append(mode)
    if attempt.get("result") == "abandoned":
        modes.append("early_stopping")
    if attempt.get("result") == "build_failed":
        modes.append("compilation_error")
    return modes if modes else ["unknown"]


def planner_node(state: UnifiedState) -> UnifiedState:
    """
    增强版 planner: 扫描 sorry + 分析失败模式 + 生成非形式化指引
    """
    ws = state["workspace_path"]
    if not ws or not Path(ws).exists():
        print("[archon] 未提供 Lean 项目路径")
        state["stage"] = "COMPLETE"
        return state

    state["loop_count"] += 1
    sorries = _scan(ws)
    print(f"[archon] planner loop#{state['loop_count']}: {len(sorries)} sorries")

    if not sorries:
        state["stage"] = "COMPLETE"
        return state

    # ── 分析 attempt_history → 识别失败模式 ──
    state["failure_modes"] = {}
    state["previous_strategies"] = {}
    all_attempts = state.get("attempt_history", [])

    for s in sorries:
        fn = s["file"]
        file_attempts = [a for a in all_attempts if a["file"] == fn]
        if not file_attempts:
            continue

        state["previous_strategies"][fn] = list({a.get("strategy", "?") for a in file_attempts})
        recent = file_attempts[-3:]
        modes = set()
        for a in recent:
            for m in _classify_failure(a):
                modes.add(m)
        state["failure_modes"][fn] = list(modes)
        if modes:
            print(f"[archon] ⚠ {fn}: {modes}")

    # ── 构建提示词上下文 ──
    files = _bash("find . -name '*.lean' -not -path './.lake/*'", ws).stdout

    failure_parts = []
    for s in sorries:
        fn = s["file"]
        modes = state.get("failure_modes", {}).get(fn, [])
        strategies = state.get("previous_strategies", {}).get(fn, [])
        if modes or strategies:
            line = f"  {fn}"
            if modes:
                line += f"\n    失败模式: {', '.join(modes)}"
            if strategies:
                line += f"\n    已尝试: {', '.join(strategies)}"
            failure_parts.append(line)
    failure_ctx = "\n".join(failure_parts)

    # ── 让模型生成解析和指引 ──
    prompt = (
        f"## 项目文件\n{files}"
        f"\n## 待填充的 sorry\n" + "\n".join(s["context"] for s in sorries)
    )
    if failure_ctx:
        prompt += f"\n## 历史失败\n{failure_ctx}"
    prompt += (
        "\n## 任务\n"
        "对每个 sorry，按以下格式输出：\n"
        "FILE|PRIORITY|PROOF_HINT|TACTIC\n\n"
        "字段: FILE(路径全匹配) | PRIORITY(high/medium/low) | "
        "PROOF_HINT(2-4句非形式化证明指引) | TACTIC(建议策略)\n"
        "有历史失败的请换策略。不要输出 Lean 代码。"
    )

    existing_hints = state.get("informal_hints", {})
    if existing_hints:
        hint_lines = [f"  {k}: {v}" for k, v in existing_hints.items()]
        prompt += f"\n## 已有指引\n" + "\n".join(hint_lines)

    resp = _model().invoke([HumanMessage(content=prompt)])

    # ── 解析输出 ──
    hints = {}
    for line in str(resp.content).strip().split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            for s in sorries:
                sf = s["file"]
                if parts[0] in sf or sf in parts[0]:
                    hint = parts[2]
                    if len(parts) >= 4 and parts[3]:
                        hint += f"\n策略建议: {parts[3]}"
                    hints[sf] = hint
                    break

    state["informal_hints"] = hints
    state["pending"] = sorries
    state["stage"] = "PROVER"
    print(f"[archon] planner: {len(hints)} hints generated")
    return state


def prover_node(state: UnifiedState) -> UnifiedState:
    """
    增强版 prover: 使用 planner 指引 + 识别失败模式 + 记录尝试历史
    """
    ws = state["workspace_path"]
    if not ws:
        return state

    pending = state.get("pending", [])
    hints = state.get("informal_hints", {})
    failure_modes = state.get("failure_modes", {})
    informal_proof = state.get("informal_proof", "")
    done = []

    for t in pending:
        f = t["file"]
        path = Path(ws) / f
        if not path.exists() or "sorry" not in path.read_text():
            if f not in state.get("completed", []):
                done.append(f)
            continue

        line = t.get("line", "?")
        file_content = path.read_text()
        print(f"[archon] prove: {f} (line {line})")

        # ── 收集指引上下文 ──
        hint = hints.get(f, "")
        fail_modes = failure_modes.get(f, [])
        rethlas_ctx = f"\n\n非形式化证明参考:\n{informal_proof}" if informal_proof else ""
        planner_hint = f"\n\n证明指引:\n{hint}" if hint else ""

        # 根据失败模式调整
        mode_advice = ""
        if "missing_infrastructure" in fail_modes:
            mode_advice = "避免依赖不存在的引理，尝试 induction/recursion 基础方法。"
        if "typeclass" in fail_modes:
            mode_advice = "显式提供类型类实例 (haveI/letI)，或在证明块内构造临时实例。"
        if "wrong_construction" in fail_modes:
            mode_advice = "重新检查类型签名，确保构造与声明一致。"
        if "early_stopping" in fail_modes:
            mode_advice = "不要过早放弃。将问题分解为更小的子目标逐步解决。"

        mode_ctx = f"\n注意: {mode_advice}" if mode_advice else ""

        # ── 主尝试 ──
        sys_msg = (
            f"你是 Lean4 形式化证明助手。根据给定的指引，"
            f"将文件中的 `sorry` 替换为正确且完整的 Lean 证明。"
            f"{rethlas_ctx}{planner_hint}{mode_ctx}"
        )
        resp = _model().invoke([
            SystemMessage(content=sys_msg),
            HumanMessage(content=f"文件 {f}:\n```lean\n{file_content}\n```"),
        ])
        code = _extract_code(str(resp.content))
        result_status = ""
        lean_error = ""

        if code and "sorry" not in code:
            _write(ws, f, code)
            ok, verrors = _verify_file(ws, f)
            if ok:
                print(f"[archon] ✅ {f} (per-file lean)")
                done.append(f)
                state["attempt_history"].append({
                    "file": f, "line": line, "loop": state["loop_count"],
                    "strategy": "direct_with_context",
                    "result": "success", "lean_error": "", "failure_mode": "",
                })
                continue
            else:
                result_status = "build_failed"
                lean_error = _format_errors(verrors)
                print(f"[archon] ⚠ {f} per-file lean failed ({len(verrors)} error(s))")
        else:
            result_status = "no_valid_code"
            lean_error = "LLM did not return valid Lean code"

        # ── 卡住 → 推理模型 fallback（结构化错误） ──
        print(f"[archon] ⚠ {f} stuck, calling reasoner...")
        reasoner_prompt = f"Prove in Lean:\n{_read(ws, f)}"
        if lean_error:
            reasoner_prompt += f"\n\n## Lean Errors (structured)\n{lean_error}"
        if hint:
            reasoner_prompt += f"\n\n## Hint\n{hint}"

        hint_resp = _model(think=True).invoke([
            SystemMessage(content="Provide an informal proof sketch."),
            HumanMessage(content=reasoner_prompt),
        ])

        fallback_msg = "Use the hint to fill the sorry with correct Lean code."
        if fail_modes:
            fallback_msg += f" Avoid previous failures: {', '.join(fail_modes)}."
        if lean_error and result_status == "build_failed":
            fallback_msg += f"\n\nPrevious Lean errors:\n{lean_error}"

        resp2 = _model().invoke([
            SystemMessage(content=fallback_msg),
            HumanMessage(content=f"Hint:\n{hint_resp.content}\n\n```lean\n{_read(ws, f)}\n```"),
        ])
        code2 = _extract_code(str(resp2.content))

        result_status = "abandoned"
        if code2 and "sorry" not in code2:
            _write(ws, f, code2)
            ok, verrors2 = _verify_file(ws, f)
            if ok:
                print(f"[archon] ✅ {f} (retry, per-file lean)")
                done.append(f)
                state["attempt_history"].append({
                    "file": f, "line": line, "loop": state["loop_count"],
                    "strategy": "reasoner_fallback",
                    "result": "success", "lean_error": "", "failure_mode": "",
                })
                continue
            else:
                result_status = "build_failed"
                lean_error = _format_errors(verrors2)
        else:
            result_status = "abandoned"

        # ── 记录失败 ──
        fm = _classify_failure({"result": result_status, "lean_error": lean_error})
        state["attempt_history"].append({
            "file": f, "line": line, "loop": state["loop_count"],
            "strategy": "direct_then_reasoner",
            "result": result_status, "lean_error": lean_error[:500],
            "failure_mode": ",".join(fm),
        })
        print(f"[archon] ❌ {f}: {result_status}")

    state["completed"].extend(done)
    state["pending"] = [t for t in pending if t["file"] not in done]
    return state


def reviewer_node(state: UnifiedState) -> UnifiedState:
    """reviewer: lake build 验证 + 失败分析 + 路由决策"""
    ws = state["workspace_path"]
    if not ws:
        state["stage"] = "COMPLETE"
        return state

    ok, log = _build(ws)
    n = _sorries(ws)

    # ── 审查摘要 ──
    done_count = len(state.get("completed", []))
    total_attempts = len(state.get("attempt_history", []))
    all_modes = {}
    for a in state.get("attempt_history", []):
        for m in a.get("failure_mode", "").split(","):
            m = m.strip()
            if m:
                all_modes[m] = all_modes.get(m, 0) + 1

    failure_summary = ""
    if all_modes:
        sorted_m = sorted(all_modes.items(), key=lambda x: -x[1])
        failure_summary = " | ".join(f"{m}({c})" for m, c in sorted_m)

    r = f"Build: {'PASS' if ok else 'FAIL'}, sorries: {n}, 尝试: {total_attempts}"
    if failure_summary:
        r += f"\n失败模式: {failure_summary}"
    state["review"] = r
    print(f"[archon] review: {r}")

    if ok and n == 0:
        state["stage"] = "COMPLETE"
        print(f"[archon] ✅ 全部证明通过 Lean 编译验证")
    elif state["loop_count"] >= state["max_loops"]:
        # Archon 内部循环耗尽 → 送回 Rethlas
        state["archon_feedback"] = log[-4000:]
        state["archon_outer_cycles"] += 1
        print(f"[archon] ⚠ 形式化失败({state['loop_count']}次), 送 Rethlas")
    else:
        print(f"[archon] 继续 Archon 内部循环 (loop {state['loop_count']}/{state['max_loops']})")
    return state


# ═══════════════════════════════════════════════════════════════════════
# 节点：review_agent_node（新增——证明期刊与推荐）
# ═══════════════════════════════════════════════════════════════════════


def review_agent_node(state: UnifiedState) -> UnifiedState:
    """审查代理：分析尝试历史，写入 journal 文件"""
    ws = state["workspace_path"]
    if not ws or not Path(ws).exists():
        return state

    loop = state["loop_count"]
    attempts = state.get("attempt_history", [])
    pending = state.get("pending", [])
    completed = state.get("completed", [])
    failure_modes = state.get("failure_modes", {})

    journal_root = Path(ws) / ".archon-journal"
    session_dir = journal_root / f"session_{loop}"
    session_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    file_groups: dict[str, list[dict]] = {}
    for a in attempts:
        fn = a["file"]
        file_groups.setdefault(fn, []).append(a)

    all_files = set(file_groups.keys()) | {s["file"] for s in pending} | set(completed)

    milestones: list[dict] = []
    summary_lines = [
        f"# Session {loop} — 审查报告 (Unified Prover)", f"",
        f"时间: {now}", f"循环: #{loop}", f"",
        "## 概览", f"",
    ]
    rec_lines = [f"# Session {loop} — 推荐", f"", "## 优先级", f""]

    sorries_before = len(pending) + len(completed)
    sorries_after = len(pending)
    summary_lines.extend([
        f"- 本轮前 sorry: {sorries_before}",
        f"- 本轮后 sorry: {sorries_after}",
        f"- 本轮完成: {len(completed)}",
        f"- 总尝试: {len(attempts)}", f"",
    ])

    blocked: list[str] = []
    for fn in sorted(all_files):
        fn_atts = file_groups.get(fn, [])
        fn_modes = failure_modes.get(fn, [])
        is_solved = fn in completed

        if fn_atts:
            last = fn_atts[-1]
            status = "solved" if is_solved else "blocked" if last.get("result") == "abandoned" else "partial"
        else:
            status = "not_started"

        if status == "blocked":
            blocked.append(fn)

        attempt_details = []
        for i, a in enumerate(fn_atts):
            attempt_details.append({
                "attempt": i + 1,
                "strategy": a.get("strategy", "?"),
                "lean_error": a.get("lean_error", "")[:300],
                "result": a.get("result", "?"),
                "insight": f"失败模式: {', '.join(fn_modes)}" if fn_modes and a["result"] != "success" else "",
            })

        next_steps_map = {
            "missing_infrastructure": "换策略：尝试 induction/recursion 基础方法",
            "typeclass": "显式提供 haveI/letI 实例",
            "wrong_construction": "重新检查类型签名",
            "early_stopping": "分解为更小子目标",
        }
        next_steps = "继续尝试"
        for mode, step in next_steps_map.items():
            if mode in fn_modes:
                next_steps = step
                break
        if status == "solved":
            next_steps = "已验证通过"

        milestones.append({
            "timestamp": now,
            "status": status,
            "target": {"file": fn, "theorem": ""},
            "session": {"id": f"session_{loop}", "model": "deepseek-v4"},
            "findings": {
                "blocker": ", ".join(fn_modes) if status != "solved" else "",
                "key_lemmas_used": [a.get("strategy", "") for a in fn_atts if a["result"] == "success"],
            },
            "attempts": attempt_details,
            "next_steps": next_steps,
        })

        summary_lines.append(f"### {fn}")
        summary_lines.append(f"- 状态: {status} | 尝试: {len(fn_atts)} | 模式: {', '.join(fn_modes) or '无'}")
        for d in attempt_details:
            err = d["lean_error"][:100] if d["lean_error"] else "-"
            summary_lines.append(f"  - Attempt {d['attempt']}: [{d['result']}] {d['strategy'][:60]}")
        summary_lines.append(f"")

        if status in ("blocked", "partial"):
            rec_lines.append(f"### {'❌' if status == 'blocked' else '🔄'} {fn}")
            rec_lines.append(f"- 建议: {next_steps}")

    (session_dir / "summary.md").write_text("\n".join(summary_lines))
    with open(session_dir / "milestones.jsonl", "w") as f:
        for m in milestones:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    if blocked:
        rec_lines.append(f"\n## 阻塞列表\n" + "\n".join(f"- {fn}" for fn in blocked))
    (session_dir / "recommendations.md").write_text("\n".join(rec_lines))

    status_lines = [
        f"# Project Status (更新于 {now})", f"",
        f"## 总体进展",
        f"- 总 sorry: {sorries_after}",
        f"- 本轮解决: {len(completed)}",
        f"- 总尝试: {len(attempts)}", f"",
        f"## 已知阻塞",
    ]
    status_lines += [f"- `{fn}`: {', '.join(failure_modes.get(fn, []))}" for fn in blocked] or ["- (无)"]
    (journal_root / "PROJECT_STATUS.md").write_text("\n".join(status_lines))

    print(f"[review-agent] 期刊已写入 {session_dir}: {len(milestones)} 文件")
    return state


def route_archon(state: UnifiedState) -> str:
    """Archon 路由: COMPLETE / 经 review_agent 重试 / 送回 Rethlas"""
    if state["stage"] == "COMPLETE":
        return END
    if state.get("archon_feedback"):
        return "generator"       # 送回 Rethlas 修复非形式化证明
    return "review_agent_node"   # Archon 内部重试（先经审查代理）


# ═══════════════════════════════════════════════════════════════════════
# 构建统一图
# ═══════════════════════════════════════════════════════════════════════


def build_unified_graph():
    w = StateGraph(UnifiedState)

    # Rethlas 节点 (保留原 Agent 工作流)
    w.add_node("search", search_node)
    w.add_node("generator", generator_node)
    w.add_node("verifier", verifier_node)
    w.add_node("rethlas_report", failure_report_node)

    # Archon 节点 (保留原 Agent 工作流)
    w.add_node("planner", planner_node)
    w.add_node("prover", prover_node)
    w.add_node("reviewer", reviewer_node)
    w.add_node("review_agent_node", review_agent_node)

    # 入口
    w.set_entry_point("search")

    # Rethlas 边: search → generate → verify → (generate|planner|report)
    w.add_edge("search", "generator")
    w.add_edge("generator", "verifier")
    w.add_conditional_edges("verifier", route_rethlas, {
        "generator": "generator",
        "planner": "planner",
        "rethlas_report": "rethlas_report",
    })
    w.add_edge("rethlas_report", END)

    # Archon 边: planner → prover → reviewer
    # reviewer → generator(Lean FAIL→Rethlas修复) | review_agent_node(审查) | END
    w.add_edge("planner", "prover")
    w.add_edge("prover", "reviewer")
    w.add_conditional_edges("reviewer", route_archon, {
        "generator": "generator",     # Lean 错误 → Rethlas 阅读理解并修复
        "review_agent_node": "review_agent_node",  # 审查后重试
        END: END,                      # COMPLETE
    })
    w.add_edge("review_agent_node", "planner")

    return w.compile()


def run_unified_workflow(statement: str, workspace_path: str = "",
                         max_loops: int = 5) -> dict:
    return build_unified_graph().invoke(
        fresh_state(statement, workspace_path, max_loops),
        {"configurable": {"thread_id": "unified-proof"}},
    )
