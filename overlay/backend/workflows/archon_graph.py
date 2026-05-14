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

import concurrent.futures
import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Annotated, Literal

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from deerflow.config.app_config import get_app_config
from deerflow.models import create_chat_model
from deerflow.mcp.cache import get_cached_mcp_tools

# R1/R2 修复: 使用 DeerFlow Sandbox 替代直接 subprocess/Path I/O
try:
    from deerflow.sandbox.sandbox_provider import get_sandbox_provider
    _SANDBOX_AVAILABLE = True
except Exception:
    _SANDBOX_AVAILABLE = False


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
# 配置 / 技能 / 工具函数
# ═══════════════════════════════════════════════════════════════════════


_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills" / "custom"


def _get_model_name() -> str:
    """从 DeerFlow 配置读取默认模型名（Y3 修复：消除硬编码）。"""
    try:
        return get_app_config().models[0].name
    except Exception:
        return "deepseek-v4"


def _load_skill_content(skill_name: str) -> str:
    """加载 DeerFlow skills 目录下的 SKILL.md 内容（R4 修复）。"""
    skill_path = _SKILLS_DIR / skill_name / "SKILL.md"
    if skill_path.exists():
        return skill_path.read_text()
    return ""


_DEFAULT_SKILL = _load_skill_content("archon-lean4")


def _load_skills_deerflow() -> str:
    """G2: 通过 DeerFlow 原生 skills storage 加载技能内容。"""
    try:
        from deerflow.skills.storage import get_or_new_skill_storage
        storage = get_or_new_skill_storage()
        skills = storage.load_skills(enabled_only=False)
        parts = []
        for s in skills:
            if s.name in ("archon-lean4",):
                content = s.skill_file.read_text() if s.skill_file.exists() else ""
                if content.startswith("---"):
                    _, _, body = content.partition("---")
                    _, _, body = body.partition("---")
                    content = body.strip()
                if content:
                    parts.append(f"## {s.name}\n{content}")
        return "\n\n".join(parts)
    except Exception as e:
        print(f"[skills] ⚠ DeerFlow skills storage 不可用: {e}")
        return _DEFAULT_SKILL


def _bash(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    """
    R2 修复: 通过 DeerFlow Sandbox 执行命令。
    开发环境回退到直接 subprocess。
    """
    if _SANDBOX_AVAILABLE:
        try:
            provider = get_sandbox_provider()
            sandbox_id = provider.acquire("archon-workflow")
            sb = provider.get(sandbox_id)
            if sb:
                full_cmd = f"cd {cwd} 2>/dev/null; {cmd}" if cwd else cmd
                result = sb.execute_command(full_cmd)
                return subprocess.CompletedProcess(
                    args=["sandbox", cmd],
                    returncode=0 if not result.startswith("Error:") else 1,
                    stdout=result if not result.startswith("Error:") else "",
                    stderr=result if result.startswith("Error:") else "",
                )
        except Exception as e:
            pass  # fallback
    # Fallback: 直接执行
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
    """R1 修复: 通过 Sandbox 读取文件，回退到直接 Path I/O。"""
    if _SANDBOX_AVAILABLE:
        try:
            provider = get_sandbox_provider()
            sandbox_id = provider.acquire("archon-workflow")
            sb = provider.get(sandbox_id)
            if sb:
                return sb.read_file(str(Path(ws) / f))
        except Exception:
            pass
    p = Path(ws) / f
    return p.read_text() if p.exists() else ""


def _write(ws: str, f: str, content: str) -> None:
    """R1 修复: 通过 Sandbox 写入文件，回退到直接 Path I/O。"""
    if _SANDBOX_AVAILABLE:
        try:
            provider = get_sandbox_provider()
            sandbox_id = provider.acquire("archon-workflow")
            sb = provider.get(sandbox_id)
            if sb:
                sb.write_file(str(Path(ws) / f), content)
                return
        except Exception:
            pass
    (Path(ws) / f).write_text(content)


def _model(name=None, think=False):
    if name is None:
        name = _get_model_name()
    return create_chat_model(name, thinking_enabled=think)


def _make_attempt(file: str, line: str, loop: int, strategy: str, result: str,
                  lean_error: str = "", failure_mode: str = "", **kw) -> dict:
    """Item 7: 创建 attempt 记录，自动添加时间戳。"""
    return {
        "file": file, "line": line, "loop": loop,
        "strategy": strategy, "result": result,
        "lean_error": lean_error, "failure_mode": failure_mode,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **kw,
    }


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
# Phase 2：目标提取 + 语义搜索
# ═══════════════════════════════════════════════════════════════════════


_SEARCH_URL = "https://leansearch.net/thm/search"


# ═══════════════════════════════════════════════════════════════════════
# Y2/Y6: DeerFlow 工具集成 + 安全调用
# ═══════════════════════════════════════════════════════════════════════


_PATHS: dict[str, Path] = {}  # G3: 路径缓存


def _resolve_path(name: str, default: Path) -> Path:
    """G3: 可配置路径解析。从环境变量读取，失败则返回默认值。"""
    if name not in _PATHS:
        env_val = os.environ.get(f"ARCHON_{name.upper()}_PATH")
        if env_val:
            _PATHS[name] = Path(env_val)
        else:
            _PATHS[name] = default
    return _PATHS[name]


def _get_all_tools() -> list:
    """Y2: 获取 DeerFlow 所有可用工具（含 sandbox + MCP + builtin）。

    替代 `_get_lsp_tools()`：通过 `get_available_tools()` 统一入口获取
    sandbox 工具（read_file/write_file/bash）、配置工具（web_search）、
    MCP 工具（lean-lsp）等全部 34 个工具。
    """
    try:
        from deerflow.tools import get_available_tools
        tools = get_available_tools()
        return tools if tools else []
    except Exception as e:
        print(f"[tools] ⚠ 无法加载 DeerFlow 工具: {e}")
        # 回退到纯 MCP 工具
        try:
            return get_cached_mcp_tools()
        except Exception:
            return []


def _safe_invoke(messages: list, model_name: str | None = None,
                 max_turns: int = 3, retries: int = 2) -> str:
    """Y6: 安全模型调用，含重试 + 超时保护。

    用 `get_all_tools()` 绑定全部 34 个 DeerFlow 工具（Y2），
    自动处理 tool call 循环，失败时自动重试。
    """
    tools = _get_all_tools()
    model = create_chat_model(model_name).bind_tools(tools) if tools else create_chat_model(model_name)

    for attempt in range(retries + 1):
        try:
            history = list(messages)
            for turn in range(max_turns):
                response = model.invoke(history)
                history.append(response)

                if not getattr(response, "tool_calls", None):
                    return str(response.content) if response.content else ""

                for tc in response.tool_calls:
                    tool = next((t for t in tools if t.name == tc["name"]), None)
                    if tool:
                        try:
                            result_str = str(tool.invoke(tc["args"]))[:3000]
                        except Exception as e:
                            result_str = f"Tool error: {e}"
                        history.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
                    else:
                        history.append(ToolMessage(
                            content=f"Unknown tool: {tc['name']}",
                            tool_call_id=tc["id"],
                        ))

            return str(response.content) if response.content else ""
        except Exception as e:
            if attempt < retries:
                print(f"[safe] ⚠ 调用失败 (attempt {attempt+1}/{retries+1}): {e}")
                continue
            print(f"[safe] ❌ 调用失败 ({retries+1} 次重试耗尽): {e}")
            return ""


# ═══════════════════════════════════════════════════════════════════════
# G1: 并行文件证明（concurrent.futures）
# ═══════════════════════════════════════════════════════════════════════


def _prove_single_file(ws: str, f: str, line: str, hint: str,
                       fail_modes: list, goal_sig: str,
                       sys_instructions: str, loop_count: int) -> dict:
    """G1: 单个文件的证明流程，供 ThreadPoolExecutor 调用。

    返回 attempt 记录字典，而非修改共享状态。
    主线程负责将结果合并到 state。
    """
    from deerflow.models import create_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage

    path = Path(ws) / f
    if not path.exists():
        return {"file": f, "line": line, "result": "skipped", "note": "file not found"}

    content = path.read_text()
    if "sorry" not in content:
        return {"file": f, "line": line, "result": "no_sorries"}

    # 级联
    cascade_ok, tactics = _try_tactics_cascade_all(ws, f)
    if cascade_ok:
        return {
            "file": f, "line": line, "loop": loop_count,
            "strategy": f"tactics_cascade:{','.join(tactics)}",
            "result": "success", "lean_error": "", "failure_mode": "",
        }

    # 剩余 sorries → LLM
    content = Path(ws, f).read_text()
    if "sorry" not in content:
        return {"file": f, "line": line, "result": "no_sorries"}

    user_content = f"File {f}:\n```lean\n{content}\n```"
    if hint:
        user_content = (
            f"根据以下非形式化证明指引填充该文件的 `sorry`。\n\n"
            f"## 证明指引\n{hint}\n\n"
            f"## 文件 {f}:\n```lean\n{content}\n```"
        )

    resp_text = _safe_invoke([
        SystemMessage(content=sys_instructions),
        HumanMessage(content=user_content),
    ])
    if not resp_text:
        return {"file": f, "line": line, "loop": loop_count,
                "strategy": "llm_failed", "result": "abandoned",
                "lean_error": "_safe_invoke returned empty", "failure_mode": "llm_error"}

    code = _extract(resp_text)
    if code and "sorry" not in code:
        _write(ws, f, code)
        ok, verrors = _verify_file(ws, f)
        if ok:
            return {
                "file": f, "line": line, "loop": loop_count,
                "strategy": f"llm_with_hints" if hint else "llm",
                "result": "success", "lean_error": "", "failure_mode": "",
            }
        else:
            # 失败 → reasoner
            return _prove_with_reasoner(ws, f, line, hint, fail_modes,
                                        goal_sig, loop_count, code, _format_errors(verrors))

    return {"file": f, "line": line, "loop": loop_count,
            "strategy": "llm", "result": "abandoned",
            "lean_error": "no_valid_code", "failure_mode": ""}


def _prove_with_reasoner(ws, f, line, hint, fail_modes, goal_sig, loop_count, code, lean_error):
    """Reasoner fallback for a single file (extracted for G1)."""
    print(f"[prove] ⚠ {f} stuck, calling reasoner...")
    reasoner_prompt = f"Prove this in Lean:\n{_read(ws, f)}\n\n"
    if goal_sig:
        reasoner_prompt += f"## 目标定理\n{goal_sig}\n\n"
    if lean_error:
        reasoner_prompt += f"## Lean 编译错误（结构化）\n{lean_error}\n\n"
    if hint:
        reasoner_prompt += f"## 证明指引\n{hint}\n\n"

    hint_resp = _model(think=True).invoke([
        SystemMessage(content="Provide an informal proof sketch in natural language."),
        HumanMessage(content=reasoner_prompt),
    ])

    fallback_prompt = "Use the informal hint to fill the `sorry` with correct Lean code."
    if fail_modes:
        fallback_prompt += f"\n\n避免之前的失败模式: {', '.join(fail_modes)}"

    resp2 = _safe_invoke([
        SystemMessage(content=fallback_prompt),
        HumanMessage(content=f"Hint:\n{hint_resp.content}\n\nFile:\n```lean\n{_read(ws, f)}\n```"),
    ])
    code2 = _extract(resp2)

    if code2 and "sorry" not in code2:
        _write(ws, f, code2)
        ok, verrors2 = _verify_file(ws, f)
        if ok:
            return {
                "file": f, "line": line, "loop": loop_count,
                "strategy": "reasoner_fallback",
                "result": "success", "lean_error": "", "failure_mode": "",
            }
        else:
            return {"file": f, "line": line, "loop": loop_count,
                    "strategy": "reasoner_fallback",
                    "result": "build_failed", "lean_error": _format_errors(verrors2),
                    "failure_mode": ",".join(_classify_failure({"result": "build_failed", "lean_error": lean_error}))}

    return {"file": f, "line": line, "loop": loop_count,
            "strategy": "llm_then_reasoner",
            "result": "abandoned", "lean_error": "no_valid_code",
            "failure_mode": ",".join(_classify_failure({"result": "abandoned", "lean_error": ""}))}


def _extract_goal(ws: str, f: str, line_str: str) -> dict:
    """Extract the theorem/lemma context around a sorry.

    Scans backward from the sorry line to find the enclosing
    theorem/lemma/def declaration, then returns its signature
    and surrounding context lines.

    Returns: {"signature": str, "line": int, "source_lines": [str]}
    """
    try:
        target_line = int(line_str)
    except (ValueError, TypeError):
        return {"signature": "", "line": 0, "source_lines": []}

    path = Path(ws) / f
    if not path.exists():
        return {"signature": "", "line": 0, "source_lines": []}

    lines = path.read_text().split("\n")

    # Scan backward from target_line to find declaration start
    # Matching: theorem | lemma | def | example | instance | corollary
    decl_start = -1
    decl_pattern = re.compile(
        r'^\s*(theorem|lemma|def|example|instance|corollary|class|structure|abbrev)\b'
    )
    for i in range(min(target_line, len(lines)) - 1, -1, -1):
        if decl_pattern.match(lines[i]):
            decl_start = i
            break

    if decl_start == -1:
        return {"signature": "", "line": target_line, "source_lines": lines}

    # Collect declaration lines until the next declaration or blank line
    decl_lines = []
    for i in range(decl_start, min(decl_start + 30, len(lines))):
        decl_lines.append(lines[i])
        if i >= target_line - 1:
            break
        # Stop if we see the start of a new declaration at same or less indent
        if i > decl_start and decl_pattern.match(lines[i]):
            break

    signature = "\n".join(decl_lines).strip()

    # Context: 5 lines before decl, 5 lines after the sorry
    ctx_before = lines[max(0, decl_start - 5):decl_start]
    ctx_after = lines[target_line:min(target_line + 5, len(lines))]

    return {
        "signature": signature,
        "line": target_line,
        "source_lines": ctx_before + ["--- [declaration] ---"] + decl_lines + ["--- [after sorry] ---"] + ctx_after,
    }


def _local_lean_search(query: str, ws: str, max_results: int = 15) -> list[dict]:
    """Local search for Lean declarations matching query.

    原版对应：lean_local_search() — 使用 ripgrep 的快速本地搜索。
    移植版用 grep 降级，搜索项目文件 + mathlib 子目录 + Lean stdlib。
    返回: [{name, kind, file}, ...] 按相关性排序。
    """
    # 声明匹配模式（与原版 lean_local_search 相同）
    decl_kinds = r"theorem|lemma|def|axiom|class|instance|structure|inductive|abbrev|opaque"
    pattern = (
        rf"^\s*(?:{decl_kinds})\s+"
        rf"(?:[A-Za-z0-9_\'.]+\.)*{re.escape(query)}[A-Za-z0-9_\'.]*(?:\s|:)"
    )

    matches: list[dict] = []

    def _grep_search(grep_dir: str, label: str) -> None:
        nonlocal matches
        remaining = max_results * 6 - len(matches)
        if remaining <= 0:
            return
        r = _bash(
            f"grep -rnHP '{pattern}' --include='*.lean' . | head -{remaining}",
            grep_dir,
        )
        for line in r.stdout.strip().split("\n"):
            parts = line.split(":", 2)
            if len(parts) >= 2:
                text = parts[2] if len(parts) > 2 else ""
                m = re.match(rf"^\s*(\w+)\s+([A-Za-z0-9_.\']+)", text)
                if m:
                    matches.append({"name": m.group(2), "kind": m.group(1), "file": f"{label}:{parts[0]}"})

    # 1. 搜索项目文件（排除 .lake）
    _grep_search(ws, "project")

    # 2. 搜索 mathlib 特定子目录（不全搜，只搜主要目录）
    for subdir in ["Algebra", "Analysis", "Data", "Logic", "SetTheory", "Topology", "NumberTheory"]:
        tp = Path(ws) / ".lake/packages/mathlib/Mathlib" / subdir
        if tp.exists():
            _grep_search(str(tp), f"mathlib/{subdir}")

    # 3. 搜索 Lean stdlib
    lean_prefix = _bash("lean --print-prefix 2>/dev/null", ws).stdout.strip()
    if lean_prefix:
        stdlib_path = Path(lean_prefix) / "src"
        if stdlib_path.exists():
            _grep_search(str(stdlib_path), "stdlib")

    # 去重 + 按相关性排序（与原版 _local_search_sort_key 一致）
    seen: set[str] = set()
    scored: list[tuple[int, int, dict]] = []
    query_lower = query.lower()
    for m in matches:
        key = f"{m['name']}|{m['kind']}"
        if key in seen:
            continue
        seen.add(key)
        name_lower = m["name"].lower()
        # 精确匹配 > 前缀匹配 > 包含匹配
        if name_lower == query_lower:
            relevance = 0
        elif name_lower.startswith(query_lower):
            relevance = 1
        elif query_lower in name_lower:
            relevance = 2
        else:
            relevance = 3
        # 项目文件优先于 mathlib 依赖
        priority = 0 if m["file"].startswith("project") else 1
        scored.append((relevance, priority, m))

    scored.sort(key=lambda x: (x[0], x[1], x[2]["name"]))
    return [m for _, _, m in scored[:max_results]]


def _search_mathlib(query: str, max_results: int = 5) -> list[dict]:
    """Search mathlib for theorems related to the query via leansearch.net."""
    try:
        import ssl
        import urllib.request
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            _SEARCH_URL,
            data=json.dumps({
                "query": query,
                "task": "retrieve useful theorems",
                "num_results": max_results,
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            return json.loads(resp.read().decode()) if resp.readable() else []
    except Exception:
        return []


def _goal_context(goals: list[dict]) -> str:
    """Format extracted goals into an LLM-readable context block."""
    lines = ["## 单文件目标分解\n"]
    for i, g in enumerate(goals):
        if not g.get("signature"):
            continue
        lines.append(f"### 目标 {i+1}: {g['file']}:{g['line']}")
        lines.append(f"```lean\n{g['signature']}\n```")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Phase 3：自动化策略级联
# ═══════════════════════════════════════════════════════════════════════


_AUTO_TACTICS = ["rfl", "simp", "ring", "linarith", "omega", "aesop", "grind"]


def _try_tactics_cascade(ws: str, f: str, content: str) -> tuple[bool, str]:
    """Try automation tactics without calling LLM.

    原版对应：automation tactics cascade — rfl→simp→ring→linarith→omega→aesop→grind。
    对每个 `sorry` 尝试用 `by {tactic}` 替换并增量编译验证。
    一旦某个策略编译通过，保留修改并返回 (True, tactic_name)。
    全部失败则将文件恢复原内容，返回 (False, "")。
    """
    if "sorry" not in content:
        return (True, "no_sorries")

    for tactic in _AUTO_TACTICS:
        new_content = content.replace("sorry", f"by {tactic}", 1)
        _write(ws, f, new_content)
        ok, _ = _verify_file(ws, f)
        if ok:
            print(f"[tactic] ✅ {f}: `{tactic}` 成功")
            return (True, tactic)

    # 全部失败，恢复原内容
    _write(ws, f, content)
    print(f"[tactic] ❌ {f}: 所有自动化策略均失败，交 LLM")
    return (False, "")


def _try_tactics_cascade_all(ws: str, f: str) -> tuple[bool, list[str]]:
    """Try tactics cascade on ALL sorries in a file, one tactic at a time.

    策略：每次替换一个 sorry 为一个 tactic，编译验证。通过则继续下一个 sorry。
    最终全部通过返回 (True, [tactic_used_each])。
    """
    content = _read(ws, f)
    tactics_used: list[str] = []

    while "sorry" in content:
        ok, tactic = _try_tactics_cascade(ws, f, content)
        if ok:
            tactics_used.append(tactic)
            content = _read(ws, f)  # 重新读取（已被修改）
        else:
            # 恢复，回退 LLM
            _write(ws, f, content)
            return (False, tactics_used)

    return (True, tactics_used)


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
    
    # ── 3. 提取每个 sorry 的精确目标 ──
    goals = []
    for s in sorries:
        g = _extract_goal(ws, s["file"], s["line"])
        if g.get("signature"):
            goals.append({"file": s["file"], "line": s["line"], "signature": g["signature"]})
    
    # ── 4. 搜索 mathlib（远程 + 本地） ──
    search_results = []
    if sorries:
        first_goal = goals[0]["signature"][:100] if goals else sorries[0]["context"][:100]
        # 远程搜索
        remote = _search_mathlib(first_goal, max_results=3)
        for r in remote[:3]:
            thm = r.get("theorem", "") or r.get("title", "")
            if thm and len(thm) < 500:
                search_results.append(f"- {thm} (remote)")
        # 本地搜索
        local = _local_lean_search(first_goal.split(":", 1)[0] if ":" in first_goal else first_goal, ws, max_results=5)
        for r in local[:5]:
            search_results.append(f"- {r['kind']} {r['name']} ({r['file']})")
    
    # ── 5. 让模型生成指引 ──
    prompt_parts = [
        f"## 项目文件\n{files}",
        f"\n## 待填充的 sorry\n" + "\n".join(s["context"] for s in sorries),
    ]
    
    # 添加精确目标上下文
    if goals:
        goal_lines = []
        for g in goals:
            goal_lines.append(f"### {g['file']}:{g['line']}")
            goal_lines.append(f"```lean\n{g['signature']}\n```")
        prompt_parts.append(f"\n## 每个 sorry 的精确定理签名（不要修改 signature 以外的内容）\n" + "\n".join(goal_lines))
    
    if failure_context:
        prompt_parts.append(f"\n## 历史失败记录（不要重复尝试这些策略）\n{failure_context}")
    
    if search_results:
        prompt_parts.append(f"\n## Mathlib 相关定理（来自 leansearch.net）\n" + "\n".join(search_results))
    
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
    全面拥抱 DeerFlow: 使用 create_deerflow_agent() 来做每个文件的证明。
    agent 自动获得 sandbox、checkpoint、中间件链、工具循环等。
    """
    from deerflow.tools import get_available_tools

    ws = state["workspace_path"]
    pending = state.get("pending", [])
    hints = state.get("informal_hints", {})
    failure_modes = state.get("failure_modes", {})
    loop_count = state["loop_count"]
    if not pending:
        return state

    print(f"[prove] 处理 {len(pending)} 个文件 (create_deerflow_agent)")
    all_tools = get_available_tools()

    for t in pending:
        f = t["file"]
        path = Path(ws) / f
        if not path.exists() or "sorry" not in path.read_text():
            continue

        line = t.get("line", "?")
        goal = _extract_goal(ws, f, line)
        goal_sig = goal.get("signature", "")
        hint = hints.get(f, "")
        fail_modes = failure_modes.get(f, [])

        cascade_ok, tactics_used = _try_tactics_cascade_all(ws, f)
        if cascade_ok:
            print(f"[prove] ✅ {f} 全部通过自动化策略: {tactics_used}")
            state["completed"].append(f)
            state["attempt_history"].append(_make_attempt(
                f, line, loop_count, f"tactics_cascade:{','.join(tactics_used)}", "success"))
            continue

        sys_prompt = "你是 Lean4 形式化证明助手。将文件中的 `sorry` 替换为正确且完整的 Lean 证明。"
        if goal_sig:
            sys_prompt += f"\n\n需要证明的目标:\n```lean\n{goal_sig}\n```"
        if hint:
            sys_prompt += f"\n\n非形式化证明指引:\n{hint}"
        skill_text = _load_skills_deerflow() or _DEFAULT_SKILL
        if skill_text:
            sys_prompt += f"\n\n## Lean 技能参考\n{skill_text[:2000]}"
        if "missing_infrastructure" in fail_modes:
            sys_prompt += "\n\n注意: 尝试 induction/recursion 基础方法。"
        if "typeclass" in fail_modes:
            sys_prompt += "\n\n注意: 显式提供 haveI/letI 实例。"
        if "wrong_construction" in fail_modes:
            sys_prompt += "\n\n注意: 重新检查类型签名。"
        if "early_stopping" in fail_modes:
            sys_prompt += "\n\n注意: 分解为更小子目标。"

        agent = create_deerflow_agent(
            model=create_chat_model(_get_model_name()),
            tools=all_tools,
            features=RuntimeFeatures(sandbox=True, loop_detection=True),
            system_prompt=sys_prompt,
            checkpointer=MemorySaver(),
            name=f"prove-{Path(f).stem}",
        )
        try:
            result = agent.invoke({"messages": [
                HumanMessage(content=(f"请处理文件 {f}。\n\n"
                    f"1. 用 read_file 读取内容\n"
                    f"2. 用 lean_goal 获取目标状态\n"
                    f"3. 用 lean_local_search 搜索引理\n"
                    f"4. 用 write_file 填写证明代码\n"
                    f"5. 用 lean_verify 编译验证\n"
                    f"6. 如果失败，检查 lean_diagnostic_messages 并修复\n"
                    f"7. 所有 sorry 通过编译后，输出文件内容")),
            ]})
            msgs = result.get("messages", [])
            last = msgs[-1] if msgs else None
            text = str(last.content) if last and hasattr(last, "content") else ""
            if text and "sorry" not in text:
                code = _extract(text)
                if code:
                    _write(ws, f, code)
                print(f"[prove] ✅ {f} (DeerFlow agent)")
                state["completed"].append(f)
                state["attempt_history"].append(_make_attempt(
                    f, line, loop_count, "deerflow_agent", "success"))
            else:
                print(f"[prove] ❌ {f} agent 未完成")
                state["attempt_history"].append(_make_attempt(
                    f, line, loop_count, "deerflow_agent", "abandoned"))
        except Exception as e:
            print(f"[prove] ❌ {f} agent 异常: {e}")
            state["attempt_history"].append(_make_attempt(
                f, line, loop_count, "deerflow_agent", "error",
                lean_error=str(e)[:500], failure_mode="agent_error"))
        del agent

    done = {a["file"] for a in state["attempt_history"] if a.get("result") == "success"}
    state["pending"] = [t for t in pending if t["file"] not in done]
    print(f"[prove] 本轮: {len(done)} 完成, {len(state['pending'])} 剩余")
    return state
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
