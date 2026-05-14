"""
Archon DeerFlow — 增强版 Plan Agent
=====================================
恢复原 Archon Plan Agent 的核心能力：
  1. 失败模式识别（缺失基础设施 / 构造错误 / 过早放弃）
  2. 非形式化证明指引生成
  3. 子目标分解 + 优先级排序
  4. Attempt 历史跟踪（记录每次策略、错误、结果）
  5. 用户提示注入接口

节点：planner (增强) → prover (增强) → reviewer (增强)
"""

import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Annotated, Literal

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.models import create_chat_model


# ═══════════════════════════════════════════════════════════════════════
# 状态 — 纯内存（增强）
# ═══════════════════════════════════════════════════════════════════════


class ArchonState(dict):
    messages: Annotated[list, add_messages]
    workspace_path: str
    stage: Literal["AUTOFORMALIZE", "PROVER", "POLISH", "COMPLETE"]
    pending: list[dict]
    completed: list[str]
    loop_count: int
    max_loops: int
    review: str

    # === 增强字段 ===
    attempt_history: list[dict]       # [{file, line, strategy, result, lean_error, failure_mode, loop}, ...]
    failure_modes: dict[str, list]    # {file: ["missing_infrastructure"|"typeclass"|"wrong_construction"|"early_stopping"|...]}
    informal_hints: dict[str, str]    # {file: "非形式化证明指引"}
    previous_strategies: dict[str, list]  # {file: ["策略已尝试列表"]}
    user_hints: str                   # 用户/审查者提供的提示


def fresh_state(ws: str, max_loops: int = 5) -> ArchonState:
    return ArchonState(
        messages=[], workspace_path=ws, stage="AUTOFORMALIZE",
        pending=[], completed=[], loop_count=0,
        max_loops=max_loops, review="",
        attempt_history=[], failure_modes={},
        informal_hints={}, previous_strategies={},
        user_hints="",
    )


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════


def _bash(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    PATH = f"{os.path.expanduser('~/.elan/bin')}:{os.environ.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True,
        timeout=300, env={**os.environ, "PATH": PATH},
    )


def _scan(ws: str) -> list[dict]:
    r = _bash("grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/'", ws)
    items = []
    for line in r.stdout.strip().split("\n"):
        parts = line.split(":", 2)
        if len(parts) >= 2:
            items.append({"file": parts[0], "line": parts[1], "context": line})
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


def _model(name="deepseek-v4", think=False):
    return create_chat_model(name, thinking_enabled=think)


def _extract(text: str) -> str:
    m = re.search(r'```(?:lean)?\s*\n?(.*?)```', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _extract_json(text: str) -> dict:
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


# ═══════════════════════════════════════════════════════════════════════
# Phase 1：增量编译 + 结构化错误解析
# ═══════════════════════════════════════════════════════════════════════


def _classify_error(msg: str) -> str:
    """Classify Lean compiler error type from error message."""
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
    """Parse Lean compiler stderr into structured error records.

    Input format (per error):
      <file>:<line>:<col>: error: <type>
      <detailed message...>

    Output:
      [{type, severity, file, line, col, message, raw}, ...]
    """
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
    """Incremental per-file verification via `lake env lean`.

    ~1-2s per file vs 5-30s for full `lake build`.
    Returns (pass, structured_errors).
    """
    r = _bash(f"lake env lean {f} 2>&1", ws)
    if r.returncode == 0:
        return (True, [])
    return (False, _parse_lean_errors(r.stderr if r.stderr else r.stdout))


def _format_errors(errors: list[dict], max_lines: int = 40) -> str:
    """Format structured errors as LLM-readable text."""
    lines = []
    for e in errors[:5]:  # 最多显示 5 个错误
        lines.append(f"{e['type']} at {e['file']}:{e['line']}:{e['col']}")
        msg_lines = e['message'].split("\n")
        for l in msg_lines[:8]:
            lines.append(f"  {l}")
        lines.append("")
    combined = "\n".join(lines)
    if len(combined) > max_lines * 80:
        combined = combined[:max_lines * 80] + "\n... (truncated)"
    return combined


# ═══════════════════════════════════════════════════════════════════════
# 失败模式分类
# ═══════════════════════════════════════════════════════════════════════


_FAILURE_KEYWORDS = {
    "missing_infrastructure": [
        "unknown identifier", "unknown constant", "unknown declaration",
        "unknown theorem", "unknown lemma", "unknown definition",
        "not found in", "has no field", "unknown namespace",
    ],
    "typeclass": [
        "failed to synthesize", "typeclass", "instance",
        "no instances", "is not a type", "has no type class",
    ],
    "wrong_construction": [
        "type mismatch", "expected", "don't know how to",
        "argument", "has type", "is not a function",
        "not a type", "unexpected",
    ],
}


def _classify_failure(attempt: dict) -> list[str]:
    """Return list of failure modes from an attempt record."""
    err = attempt.get("lean_error", "").lower()
    modes = []
    for mode, keywords in _FAILURE_KEYWORDS.items():
        if any(kw in err for kw in keywords):
            modes.append(mode)
    if attempt.get("result") == "abandoned":
        modes.append("early_stopping")
    if attempt.get("result") == "build_failed":
        modes.append("compilation_error")
    return modes if modes else ["unknown"]


# ═══════════════════════════════════════════════════════════════════════
# 节点：planner（增强）
# ═══════════════════════════════════════════════════════════════════════


def planner(state: ArchonState) -> ArchonState:
    """
    增强版 Plan Agent：
    1. 扫描 sorry
    2. 分析 attempt_history → 识别失败模式
    3. 生成非形式化证明指引 + 建议策略
    4. 按依赖关系排优先级
    5. 设置明确的子目标
    """
    ws = state["workspace_path"]
    state["loop_count"] += 1
    loop = state["loop_count"]
    print(f"[plan] === loop #{loop} ===")

    sorries = _scan(ws)
    print(f"[plan] {len(sorries)} sorries found")

    if not sorries:
        state["stage"] = "COMPLETE"
        return state

    # ── 1. 分析 attempt_history → 识别每文件的失败模式 ──
    state["failure_modes"] = {}
    state["previous_strategies"] = {}
    
    all_attempts = state.get("attempt_history", [])
    
    for s in sorries:
        fn = s["file"]
        file_attempts = [a for a in all_attempts if a["file"] == fn]
        if not file_attempts:
            continue
        
        # 识别此文件已尝试过的策略
        state["previous_strategies"][fn] = list({
            a.get("strategy", "?")
            for a in file_attempts
        })
        
        # 分析最近 3 次尝试的失败模式
        recent = file_attempts[-3:]
        modes = set()
        for a in recent:
            for m in _classify_failure(a):
                modes.add(m)
        state["failure_modes"][fn] = list(modes)
        
        if modes:
            print(f"[plan] ⚠ {fn}: 失败模式 {modes}")

    # ── 2. 构建提示词上下文 ──
    files = _bash("find . -name '*.lean' -not -path './.lake/*'", ws).stdout
    
    # 构建每文件的失败上下文
    failure_context_parts = []
    for s in sorries:
        fn = s["file"]
        modes = state.get("failure_modes", {}).get(fn, [])
        strategies = state.get("previous_strategies", {}).get(fn, [])
        
        parts = [f"  {fn}"]
        if modes:
            parts.append(f"    已识别失败模式: {', '.join(modes)}")
        if strategies:
            parts.append(f"    已尝试策略: {', '.join(strategies)}")
        if len(parts) > 1:
            failure_context_parts.append("\n".join(parts))
    
    failure_context = "\n".join(failure_context_parts)
    
    user_hint_text = state.get("user_hints", "")
    
    # ── 3. 让模型生成指引 ──
    prompt_parts = [
        f"## 项目文件\n{files}",
        f"\n## 待填充的 sorry\n" + "\n".join(s["context"] for s in sorries),
    ]
    
    if failure_context:
        prompt_parts.append(f"\n## 历史失败记录（不要重复尝试这些策略）\n{failure_context}")
    
    if user_hint_text:
        prompt_parts.append(f"\n## 用户提示\n{user_hint_text}")
    
    prompt_parts.append(
        "\n## 任务\n"
        "对上述每个 sorry，按以下格式输出分析结果，每行一个 sorry：\n"
        "FILE|PRIORITY|PROOF_HINT|TACTIC\n\n"
        "字段说明：\n"
        "- FILE: sorry 所在文件路径（必须全路径匹配）\n"
        "- PRIORITY: high/medium/low（按依赖关系排序，被依赖的先证明）\n"
        "- PROOF_HINT: 简要的非形式化证明指引（2-4句话），包含关键思路和中间步骤\n"
        "  * 如果有历史失败记录，请换一种策略\n"
        "- TACTIC: 建议使用的 Lean 策略（如 induction/simp/ring/linarith/aesop/omega/cases/exact/apply/rw）\n\n"
        "如果所有 sorry 都已有非形式化指引（informal_hints 中），请参考并完善它们。"
        "不要直接输出 Lean 代码——只输出分析结果。"
    )
    
    # 注入已有的非形式化指引（来自之前的外层 Rethlas 循环）
    existing_hints = state.get("informal_hints", {})
    if existing_hints:
        hint_lines = [f"  {k}: {v}" for k, v in existing_hints.items()]
        prompt_parts.insert(-1, f"\n## 已有的非形式化证明参考（来自 Rethlas）\n" + "\n".join(hint_lines))

    prompt = "\n".join(prompt_parts)
    
    resp = _model().invoke([HumanMessage(content=prompt)])
    output = str(resp.content)
    print(f"[plan] 模型分析完成 ({len(output)} chars)")

    # ── 4. 解析模型输出 → 设置 objectives ──
    hints: dict[str, str] = {}
    priorities: dict[str, str] = {}
    
    for line in output.strip().split("\n"):
        line = line.strip()
        if "|" not in line:
            # 尝试找类似 FILE:... 的行
            for s in sorries:
                if line.startswith(s["file"]) or s["file"] in line:
                    hints[s["file"]] = line
                    break
            continue
        
        parts = [p.strip() for p in line.split("|")]
        file_ref = parts[0]
        priority = parts[1] if len(parts) >= 2 else "medium"
        hint = parts[2] if len(parts) >= 3 else ""
        tactic = parts[3] if len(parts) >= 4 else ""
        
        # 匹配到对应的 sorry
        for s in sorries:
            sf = s["file"]
            if file_ref in sf or sf in file_ref:
                hint_with_tactic = hint
                if tactic:
                    hint_with_tactic += f"\n策略建议: {tactic}"
                hints[sf] = hint_with_tactic
                priorities[sf] = priority
                break

    # ── 5. 更新状态 ──
    state["informal_hints"] = hints
    state["pending"] = sorries
    state["stage"] = "PROVER"
    
    print(f"[plan] 生成了 {len(hints)} 个证明指引")
    if hints:
        for f, h in hints.items():
            print(f"[plan]   {f}: {h[:80]}...")
    
    # 按优先级排序 pending（不实现，但保留排序提示）
    state["pending"] = sorries
    
    return state


# ═══════════════════════════════════════════════════════════════════════
# 节点：prover（增强）
# ═══════════════════════════════════════════════════════════════════════


def prover(state: ArchonState) -> ArchonState:
    """
    增强版 Prover：
    1. 使用 planner 生成的非形式化指引
    2. 根据失败模式调整策略
    3. 记录每次尝试到 attempt_history
    """
    ws = state["workspace_path"]
    pending = state.get("pending", [])
    hints = state.get("informal_hints", {})
    failure_modes = state.get("failure_modes", {})
    done = []

    for t in pending:
        f = t["file"]
        path = Path(ws) / f
        if not path.exists():
            continue

        content = path.read_text()
        if "sorry" not in content:
            done.append(f)
            continue

        line = t.get("line", "?")
        print(f"[prove] === {f} (line {line}) ===")

        # ── 检查当前文件是否有非形式化指引 ──
        hint = hints.get(f, "")
        fail_modes = failure_modes.get(f, [])
        
        # ── 根据失败模式调整 SystemMessage ──
        sys_instructions = "Fill every `sorry` with a correct Lean 4 proof. "
        sys_instructions += "Return ONLY the complete file content. "
        sys_instructions += "Do NOT change anything outside the `sorry` blocks."
        
        if "missing_infrastructure" in fail_modes:
            sys_instructions += (
                "\n\n注意: 之前的尝试遇到了 Mathlib 中缺少所需基础设施的问题。"
                "不要依赖可能不存在的引理。"
                "如果标准方法不可行，请查阅 mathlib 中可用的等效工具，"
                "或者自己构造基础证明（induction/recursion）。"
            )
        
        if "typeclass" in fail_modes:
            sys_instructions += (
                "\n\n注意: 之前的尝试遇到了类型类合成失败。"
                "请确保显式提供所需实例（haveI/letI）。"
                "或者在证明块内构造临时实例。"
            )
        
        if "wrong_construction" in fail_modes:
            sys_instructions += (
                "\n\n注意: 之前的尝试使用了错误的构造/类型。"
                "请重新检查类型签名，确保使用的构造与声明类型一致。"
            )
        
        if "early_stopping" in fail_modes:
            sys_instructions += (
                "\n\n注意: 之前的尝试过早放弃了。"
                "这个证明是可完成的。请尝试不同的策略。"
                "如果卡住，将问题分解为更小的子目标逐一解决。"
            )
        
        # ── 注入非形式化指引 ──
        user_content = f"File {f}:\n```lean\n{content}\n```"
        
        if hint:
            # 在 HumanMessage 中包含指引
            user_content = (
                f"根据以下非形式化证明指引填充该文件的 `sorry`。\n\n"
                f"## 证明指引\n{hint}\n\n"
                f"## 文件 {f}:\n```lean\n{content}\n```"
            )
            print(f"[prove] 使用 planner 指引: {hint[:80]}...")
        
        # ── 主尝试 ──
        resp = _model().invoke([
            SystemMessage(content=sys_instructions),
            HumanMessage(content=user_content),
        ])
        code = _extract(str(resp.content))
        
        strategy_used = "direct_llm"
        result_status = ""
        lean_error = ""

        if code and "sorry" not in code:
            _write(ws, f, code)
            ok, verrors = _verify_file(ws, f)
            if ok:
                print(f"[prove] ✅ {f} (per-file lean)")
                done.append(f)
                state["attempt_history"].append({
                    "file": f, "line": line, "loop": state["loop_count"],
                    "strategy": "direct_llm_with_hints" if hint else "direct_llm",
                    "result": "success",
                    "lean_error": "",
                    "failure_mode": "",
                })
                continue
            else:
                result_status = "build_failed"
                lean_error = _format_errors(verrors)
                print(f"[prove] ⚠ {f} per-file lean failed ({len(verrors)} error(s))")
        else:
            result_status = "no_valid_code"
            lean_error = "LLM did not return valid Lean code"
        
        # ── 卡住 → 推理模型 fallback（结构化错误） ──
        print(f"[prove] ⚠ {f} stuck, calling reasoner...")
        
        reasoner_prompt = f"Prove this in Lean:\n{_read(ws, f)}\n\n"
        if lean_error:
            reasoner_prompt += f"## Lean 编译错误（结构化）\n{lean_error}\n\n"
        if hint:
            reasoner_prompt += f"## 证明指引\n{hint}\n\n"
        
        hint_resp = _model(think=True).invoke([
            SystemMessage(content="Provide an informal proof sketch in natural language."),
            HumanMessage(content=reasoner_prompt),
        ])
        
        print(f"[prove] reasoner hint: {str(hint_resp.content)[:100]}...")

        # Fallback 尝试（携带结构化错误）
        fallback_prompt = "Use the informal hint to fill the `sorry` with correct Lean code."
        if fail_modes:
            fallback_prompt += f"\n\n避免之前的失败模式: {', '.join(fail_modes)}"
        if lean_error and result_status == "build_failed":
            fallback_prompt += f"\n\n之前的 Lean 错误:\n{lean_error}"
        
        resp2 = _model().invoke([
            SystemMessage(content=fallback_prompt),
            HumanMessage(content=f"Hint:\n{hint_resp.content}\n\nFile:\n```lean\n{_read(ws, f)}\n```"),
        ])
        code2 = _extract(str(resp2.content))
        
        if code2 and "sorry" not in code2:
            _write(ws, f, code2)
            ok, verrors2 = _verify_file(ws, f)
            if ok:
                print(f"[prove] ✅ {f} (retry, per-file lean)")
                done.append(f)
                state["attempt_history"].append({
                    "file": f, "line": line, "loop": state["loop_count"],
                    "strategy": "reasoner_fallback" + ("_with_hints" if hint else ""),
                    "result": "success",
                    "lean_error": "",
                    "failure_mode": "",
                })
                continue
            else:
                result_status = "build_failed"
                lean_error = _format_errors(verrors2)
                print(f"[prove] ❌ {f} retry per-file lean failed ({len(verrors2)} error(s))")
        else:
            result_status = "abandoned"
            print(f"[prove] ❌ {f} failed, no valid code from retry")
        
        # ── 记录失败尝试 ──
        failure_mode_str = ",".join(_classify_failure({
            "result": result_status,
            "lean_error": lean_error,
        }))
        state["attempt_history"].append({
            "file": f, "line": line, "loop": state["loop_count"],
            "strategy": strategy_used + "_then_reasoner",
            "result": result_status,
            "lean_error": lean_error,
            "failure_mode": failure_mode_str,
        })

    state["completed"].extend(done)
    state["pending"] = [t for t in pending if t["file"] not in done]
    
    # 总结
    if done:
        print(f"[prove] 本轮完成: {len(done)}/{len(pending)} 个 sorry")
    if state.get("pending"):
        print(f"[prove] 剩余: {len(state['pending'])} 个 sorry")
    
    return state


# ═══════════════════════════════════════════════════════════════════════
# 节点：reviewer（增强）
# ═══════════════════════════════════════════════════════════════════════


def reviewer(state: ArchonState) -> ArchonState:
    """
    增强版 Reviewer：
    1. lake build 验证
    2. 汇总 attempt_history 生成审查摘要
    3. 分析失败模式 → 反馈给下一轮 planner
    """
    ws = state["workspace_path"]
    ok, log = _build(ws)
    n = _sorries(ws)

    # ── 生成审查摘要 ──
    done_count = len(state.get("completed", []))
    pending_count = len(state.get("pending", []))
    total_attempts = len(state.get("attempt_history", []))
    
    # 收集失败模式分布
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
    
    r = (
        f"Build: {'PASS' if ok else 'FAIL'}, "
        f"sorries: {n}, "
        f"已完成: {done_count}, "
        f"待处理: {pending_count}, "
        f"总尝试: {total_attempts}"
    )
    if failure_summary:
        r += f"\n失败模式分布: {failure_summary}"
    
    state["review"] = r
    print(f"[review] {r}")

    if ok and n == 0:
        state["stage"] = "COMPLETE"
        print(f"[review] ✅ 全部证明完成")
    elif state["loop_count"] >= state["max_loops"]:
        state["stage"] = "COMPLETE"
        print(f"[review] ⏹ 达到最大循环 {state['max_loops']}")
    
    return state


# ═══════════════════════════════════════════════════════════════════════
# 节点：review_agent（新增——证明期刊与推荐）
# ═══════════════════════════════════════════════════════════════════════


def review_agent(state: ArchonState) -> ArchonState:
    """
    审查代理：分析 prover 的尝试历史，生成结构化工件：
    - .archon-journal/session_{N}/summary.md        — 本轮详细摘要
    - .archon-journal/session_{N}/milestones.jsonl  — 每个文件的里程碑记录
    - .archon-journal/session_{N}/recommendations.md— 计划代理的行动建议
    - .archon-journal/PROJECT_STATUS.md             — 累积状态
    """
    ws = state["workspace_path"]
    if not Path(ws).exists():
        return state

    loop = state["loop_count"]
    attempts = state.get("attempt_history", [])
    pending = state.get("pending", [])
    completed = state.get("completed", [])
    failure_modes = state.get("failure_modes", {})

    # ── 创建 journal 目录 ──
    journal_root = Path(ws) / ".archon-journal"
    session_dir = journal_root / f"session_{loop}"
    session_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # ── 分析每个文件的尝试历史 ──
    file_groups: dict[str, list[dict]] = {}
    for a in attempts:
        fn = a["file"]
        if fn not in file_groups:
            file_groups[fn] = []
        file_groups[fn].append(a)

    files_from_pending = {s["file"] for s in pending}
    all_files = set(file_groups.keys()) | files_from_pending | set(completed)

    milestones: list[dict] = []
    summary_lines = [f"# Session {loop} — 审查报告", f"", f"时间: {now}", f"循环: #{loop}", f"", "## 概览", f""]
    rec_lines = [f"# Session {loop} — 推荐", f"", "## 优先级", f""]

    sorries_before = len(pending) + len(completed)
    sorries_after = len(pending)
    summary_lines.append(f"- 本轮前 sorry 数: {sorries_before}")
    summary_lines.append(f"- 本轮后 sorry 数: {sorries_after}")
    summary_lines.append(f"- 本轮完成: {len(completed)}")
    summary_lines.append(f"- 总尝试次数: {len(attempts)}")
    summary_lines.append(f"")

    closest: list[str] = []
    blocked: list[str] = []

    for fn in sorted(all_files):
        fn_atts = file_groups.get(fn, [])
        fn_modes = failure_modes.get(fn, [])
        is_solved = fn in completed

        # 提取尝试列表中的定理名（从文件的 sorry 行推测）
        theorem_hint = ""
        for s in pending:
            if s["file"] == fn:
                theorem_hint = s.get("context", "")[:80]
                break

        key_lemmas_used = []
        for a in fn_atts:
            if a["result"] == "success":
                strat = a.get("strategy", "")
                key_lemmas_used.append(strat)

        if fn_atts:
            last = fn_atts[-1]
            status = "solved" if is_solved else "partial"
            if status == "partial" and last.get("result") == "abandoned":
                status = "blocked"
        else:
            status = "not_started"

        if is_solved:
            closest.append(fn)
        elif status == "blocked":
            blocked.append(fn)
        else:
            closest.append(fn)

        # 构建 attempt 详情
        attempt_details: list[dict] = []
        for i, a in enumerate(fn_atts):
            attempt_details.append({
                "attempt": i + 1,
                "strategy": a.get("strategy", "?"),
                "lean_error": a.get("lean_error", "")[:300],
                "result": a.get("result", "?"),
                "insight": "",
            })

        # 生成 insight：从失败模式推断
        if fn_modes:
            for detail in attempt_details:
                if detail["result"] != "success":
                    detail["insight"] = f"失败模式: {', '.join(fn_modes)}"

        next_steps = ""
        if status == "solved":
            next_steps = "已验证通过"
        elif "missing_infrastructure" in fn_modes:
            next_steps = "换策略：尝试 induction/recursion 基础方法，而非依赖 Mathlib 引理"
        elif "typeclass" in fn_modes:
            next_steps = "显式提供 haveI/letI 实例，或在证明块内构造临时实例"
        elif "wrong_construction" in fn_modes:
            next_steps = "重新检查类型签名，调整构造方式"
        elif "early_stopping" in fn_modes:
            next_steps = "分解为更小子目标，逐个攻破"
        else:
            next_steps = "继续尝试，考虑换模型或增加推理深度"

        milestone = {
            "timestamp": now,
            "status": status,
            "target": {"file": fn, "theorem": theorem_hint},
            "session": {"id": f"session_{loop}", "model": "deepseek-v4"},
            "findings": {
                "blocker": ", ".join(fn_modes) if status != "solved" else "",
                "key_lemmas_used": key_lemmas_used,
            },
            "attempts": attempt_details,
            "next_steps": next_steps,
        }
        milestones.append(milestone)

        # Summary 每文件条目
        summary_lines.append(f"### {fn}")
        summary_lines.append(f"- 状态: {status}")
        summary_lines.append(f"- 尝试次数: {len(fn_atts)}")
        summary_lines.append(f"- 失败模式: {', '.join(fn_modes) if fn_modes else '无'}")
        summary_lines.append(f"- 下一步: {next_steps}")
        for d in attempt_details:
            strat = d["strategy"][:60]
            err = d["lean_error"][:100] if d["lean_error"] else "-"
            summary_lines.append(f"  - Attempt {d['attempt']}: [{d['result']}] {strat}")
            if d["lean_error"]:
                summary_lines.append(f"    错误: {err}...")
        summary_lines.append(f"")

        # Recommendations 条目
        if status == "blocked":
            rec_lines.append(f"### ❌ {fn} — 阻塞")
            rec_lines.append(f"- 原因: {', '.join(fn_modes)}")
            rec_lines.append(f"- 建议: {next_steps}")
        elif status == "partial":
            rec_lines.append(f"### 🔄 {fn} — 进行中")
            rec_lines.append(f"- 已有 {len(fn_atts)} 次尝试")
            rec_lines.append(f"- 建议: {next_steps}")

    # ── 写入 summary.md ──
    (session_dir / "summary.md").write_text("\n".join(summary_lines))

    # ── 写入 milestones.jsonl ──
    with open(session_dir / "milestones.jsonl", "w") as f:
        for m in milestones:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    # ── 写入 recommendations.md ──
    if blocked:
        rec_lines.append(f"\n## 阻塞列表\n")
        for fn in blocked:
            rec_lines.append(f"- {fn}: 不要重复指派")
    if closest:
        rec_lines.append(f"\n## 接近完成的文件\n")
        for fn in closest:
            rec_lines.append(f"- {fn}: 优先指派")
    (session_dir / "recommendations.md").write_text("\n".join(rec_lines))

    # ── 写入/更新累积 PROJECT_STATUS.md ──
    status_lines = [
        f"# Project Status (更新于 {now})",
        f"",
        f"## 总体进展",
        f"- 总 sorry: {sorries_after}",
        f"- 本轮解决: {len(completed)}",
        f"- 总尝试次数: {len(attempts)}",
        f"- 循环次数: {loop}",
        f"",
        f"## 已知阻塞（不要重复尝试）",
    ]
    for fn in blocked:
        modes = failure_modes.get(fn, [])
        status_lines.append(f"- `{fn}`: {', '.join(modes)}")
    if not blocked:
        status_lines.append(f"- (无)")
    status_lines.append(f"")
    status_lines.append(f"## 最新审查摘要")
    status_lines.append(state.get("review", ""))
    (journal_root / "PROJECT_STATUS.md").write_text("\n".join(status_lines))

    print(f"[review-agent] 期刊已写入 {session_dir}")
    print(f"[review-agent]   {len(milestones)} 文件, {len(attempts)} 尝试")

    return state


# ═══════════════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════════════


def route(state: ArchonState) -> str:
    """路径：非 COMPLETE → 先经 review_agent 再回 planner"""
    if state["stage"] == "COMPLETE":
        return END
    return "review_agent"


# ═══════════════════════════════════════════════════════════════════════
# 图
# ═══════════════════════════════════════════════════════════════════════


def build_archon_graph():
    w = StateGraph(ArchonState)
    w.add_node("planner", planner)
    w.add_node("prover", prover)
    w.add_node("reviewer", reviewer)
    w.add_node("review_agent", review_agent)
    w.set_entry_point("planner")
    w.add_edge("planner", "prover")
    w.add_edge("prover", "reviewer")
    w.add_conditional_edges("reviewer", route, {
        "review_agent": "review_agent",
        END: END,
    })
    w.add_edge("review_agent", "planner")
    return w.compile()


def run_archon_workflow(ws: str, max_loops: int = 5) -> dict:
    return build_archon_graph().invoke(
        fresh_state(ws, max_loops),
        {"configurable": {"thread_id": f"archon-{Path(ws).name}"}},
    )
