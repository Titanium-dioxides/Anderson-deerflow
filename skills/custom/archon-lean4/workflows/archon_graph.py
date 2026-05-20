"""
Archon 迁移 — LangGraph 编排工作流
=====================================
替代 archon loop 的核心编排图。基于 LangGraph StateGraph 实现
init → plan → prover → review 循环。

放置位置: /home/zdzdhd/deer-flow/backend/src/workflows/archon_graph.py
注册方式: 通过 DeerFlow Gateway 注册为可触发的工作流
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Literal, TypedDict

# LangGraph 会在 DeerFlow 的依赖中
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage

# DeerFlow 模型通道
from deerflow.models import create_chat_model

# ═══════════════════════════════════════════════════════════════════════
# 图状态定义
# ═══════════════════════════════════════════════════════════════════════


class ArchonState(TypedDict):
    """Archon 工作流状态"""

    workspace_path: str  # Lean 项目在沙箱中的绝对路径
    current_stage: Literal[
        "INIT", "AUTOFORMALIZE", "PROVER", "POLISH", "COMPLETE", "ERROR"
    ]
    pending_tasks: list[str]  # 从 task_pending.md 解析
    max_loops: int  # 防止死循环
    loop_count: int  # 当前迭代计数
    next_action: str  # 路由决策字段


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════


def _state_dir(path: str) -> Path:
    return Path(path) / ".archon"


def _read_file(path: Path) -> str:
    if path.exists():
        return path.read_text()
    return ""


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _run_bash(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    """运行 shell 命令并返回结果"""
    return subprocess.run(
        ["bash", "-c", cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=600,
        env={
            **os.environ,
            "PATH": f"{os.path.expanduser('~/.elan/bin')}:{os.environ.get('PATH', '')}",
        },
    )


def _count_sorries(workspace: str) -> int:
    """统计项目中的 sorry 数量"""
    r = _run_bash(
        "grep -rn 'sorry' --include='*.lean' . | grep -v '.lake/' | wc -l",
        workspace,
    )
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def _read_stage(workspace: str) -> str:
    """读取当前 stage"""
    progress = _state_dir(workspace) / "PROGRESS.md"
    if not progress.exists():
        return "INIT"
    text = progress.read_text()
    for line in text.splitlines():
        if line.strip() == "## Current Stage":
            # 返回下一行
            lines = text.splitlines()
            idx = lines.index(line)
            if idx + 1 < len(lines):
                return lines[idx + 1].strip().upper()
    return "INIT"


def _parse_pending_tasks(workspace: str) -> list[str]:
    """从 task_pending.md 解析待办任务列表"""
    pending = _state_dir(workspace) / "task_pending.md"
    if not pending.exists():
        return []
    text = pending.read_text()
    tasks = []
    for line in text.splitlines():
        m = re.match(r"-\s*\[\s*\]\s*(.+)", line)
        if m:
            tasks.append(m.group(1).strip())
    return tasks


def _get_template_dir() -> Path:
    """获取 Archon 模板目录（支持宿主机和 Docker 容器两种路径）"""
    candidates = [
        # Docker 容器内路径
        Path("/app/skills/custom/archon-init/templates"),
        # 宿主机 DeerFlow 路径
        Path("/home/zdzdhd/deer-flow/skills/custom/archon-init/templates"),
        # 宿主机 Archon 源路径（回退）
        Path("/home/zdzdhd/ai4math/Archon/.archon-src/archon-template"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"无法找到 Archon 模板目录。已尝试:\n"
        + "\n".join(f"  - {p}" for p in candidates)
    )


def _template_copy(filename: str, dest: Path) -> None:
    """从模板目录复制文件到目标目录"""
    tmpl = _get_template_dir() / filename
    if tmpl.exists():
        content = tmpl.read_text()
    else:
        content = _template_fallback(filename)
    dest.mkdir(parents=True, exist_ok=True)
    _write_file(dest / filename, content)


def _template_fallback(filename: str) -> str:
    """内联模板 fallback"""
    defaults = {
        "PROGRESS.md": (
            "# Project Progress\n\n"
            "## Current Stage\ninit\n\n"
            "## Stages\n"
            "- [ ] init\n- [ ] autoformalize\n- [ ] prover\n- [ ] polish\n\n"
            "## Current Objectives\n"
        ),
        "CLAUDE.md": "# Archon Project (DeerFlow Migrated)\n\n",
        "task_pending.md": "## Pending Tasks\n(none)\n",
        "task_done.md": "(none)\n",
        "USER_HINTS.md": "",
        "PROJECT_STATUS.md": "# Project Status\n\nNot started.\n",
    }
    return defaults.get(filename, "")


def _is_complete(workspace: str) -> bool:
    """检查是否所有 sorry 都已解决"""
    return _count_sorries(workspace) == 0


# ═══════════════════════════════════════════════════════════════════════
# 节点函数
# ═══════════════════════════════════════════════════════════════════════


def run_init_node(state: ArchonState) -> ArchonState:
    """≡ archon init — 初始化项目状态，使用 Archon 模板"""
    ws = state["workspace_path"]
    stdir = _state_dir(ws)
    state["current_stage"] = "INIT"
    state["loop_count"] = 0

    # 如果 .archon/ 已存在，跳过
    if stdir.exists():
        print(f"[init] .archon/ 已存在，跳过初始化")
        # 读取当前 stage
        stage = _read_stage(ws)
        state["current_stage"] = stage if stage != "INIT" else "INIT"
    else:
        # 创建 .archon/ 完整结构（使用 Archon 模板）
        stdir.mkdir(parents=True, exist_ok=True)
        (stdir / "prompts").mkdir(exist_ok=True)
        (stdir / "task_results").mkdir(exist_ok=True)
        (stdir / "proof-journal/sessions").mkdir(parents=True, exist_ok=True)
        (stdir / "informal").mkdir(exist_ok=True)

        # 从模板目录复制
        _template_copy("PROGRESS.md", stdir)
        _template_copy("CLAUDE.md", stdir)
        _template_copy("task_pending.md", stdir)
        _template_copy("task_done.md", stdir)
        _template_copy("USER_HINTS.md", stdir)
        _template_copy("PROJECT_STATUS.md", stdir)

        print(f"[init] 已从模板创建 .archon/ 目录结构")

    # 确定下一个阶段
    sorry_count = _count_sorries(ws)
    if sorry_count == 0:
        # 检查是否有 .lean 文件
        r = _run_bash("find . -name '*.lean' -not -path './.lake/*' | head -1", ws)
        has_lean = bool(r.stdout.strip())
        if has_lean:
            state["current_stage"] = "COMPLETE"
            state["next_action"] = "end"
        else:
            # 无 Lean 项目，停留在 init
            state["next_action"] = "init"
    else:
        state["current_stage"] = "AUTOFORMALIZE"
        state["next_action"] = "plan"

    return state

    # 确定下一步
    sorry_count = _count_sorries(ws)
    if sorry_count == 0:
        state["current_stage"] = "COMPLETE"
        state["next_action"] = "end"
    else:
        state["current_stage"] = "AUTOFORMALIZE"
        state["next_action"] = "plan"

    return state


def run_plan_node(state: ArchonState) -> ArchonState:
    """≡ plan agent — 扫描 sorries，排列优先级，更新任务列表"""
    ws = state["workspace_path"]
    print(f"[plan] 开始规划 (stage={state['current_stage']})")

    # 统计 sorries
    sorry_count = _count_sorries(ws)
    print(f"[plan] 发现 {sorry_count} 个 sorry")

    # 如果没有 sorries，直接完成
    if sorry_count == 0:
        state["current_stage"] = "COMPLETE"
        state["next_action"] = "end"
        return state

    # 扫描有 sorry 的文件
    r = _run_bash(
        "grep -rln 'sorry' --include='*.lean' . | grep -v '.lake/' | sort",
        ws,
    )
    files = [f.strip() for f in r.stdout.strip().split("\n") if f.strip()]

    # 更新 task_pending.md
    pending_lines = ["## Pending Tasks (prioritized)\n"]
    for f in files:
        count_r = _run_bash(
            f"grep -c 'sorry' '{f}'", ws
        )
        count = count_r.stdout.strip()
        pending_lines.append(f"- [ ] {f} — {count} sorries\n")

    _write_file(_state_dir(ws) / "task_pending.md", "".join(pending_lines))
    state["pending_tasks"] = files
    state["next_action"] = "prover"

    print(f"[plan] 已更新 task_pending.md，共 {len(files)} 个文件")
    return state


def _extract_lean_code(text: str) -> str:
    """从 LLM 响应中提取 Lean 代码，去掉 markdown 围栏"""
    # 移除 ```lean ... ``` 围栏
    m = re.search(r'```lean\s*\n?(.*?)```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 移除 ``` ... ``` 围栏（无语言标注）
    m = re.search(r'```\s*\n?(.*?)```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 没有围栏，直接返回
    return text.strip()


def _write_task_result(workspace: str, file_path: str, status: str, errors: str = "") -> None:
    """写入 task_results/<file>.md"""
    result_dir = _state_dir(workspace) / "task_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file_path.replace("/", "_").replace(".", "_") + ".md"
    result_file = result_dir / safe_name
    result_file.write_text(
        f"# {file_path}\n\n"
        f"## Status\n{status}\n\n"
        f"## Timestamp\n{_iso_ts()}\n\n"
        + (f"## Errors\n```\n{errors[-2000:]}\n```\n" if errors else "")
    )


def _iso_ts() -> str:
    """返回 ISO-8601 时间戳"""
    return subprocess.run(
        ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
        capture_output=True, text=True
    ).stdout.strip()


def _call_llm_fill_sorry(file_path: str, workspace: str, attempt: int, prev_errors: str = "") -> str | None:
    """调用 DeerFlow 模型填充文件中的 sorry。
    
    返回新文件内容（如果成功生成了），否则返回 None。
    """
    full_path = Path(workspace) / file_path
    if not full_path.exists():
        return None

    content = full_path.read_text()

    try:
        model = create_chat_model("deepseek-v4", thinking_enabled=False)
    except Exception as e:
        print(f"[prover] ⚠ 创建模型失败: {e}")
        return None

    if attempt == 0:
        messages = [
            SystemMessage(content=(
                "You are a Lean 4 theorem proving assistant. "
                "Replace every `sorry` with a complete, correct proof.\n\n"
                "RULES:\n"
                "- Return ONLY the exact same .lean file with sorries replaced.\n"
                "- Do NOT change imports, module names, theorem signatures, or any code\n"
                "  outside the proof block.\n"
                "- Do NOT add new theorems, lemmas, or declarations.\n"
                "- Do NOT modify lakefile, Makefile, or project config.\n"
                "- Do NOT add explanations, markdown, or code fences.\n"
                "- Keep the file minimal: only replace `sorry` with a proof."
            )),
            HumanMessage(content=f"Fill each `sorry` in this file with a correct proof:\n\n{content}"),
        ]
    else:
        messages = [
            SystemMessage(content=(
                "Fix this Lean file. The previous version had compilation errors.\n"
                "RULES:\n"
                "- Replace ONLY the `sorry` with a correct proof.\n"
                "- Do NOT change anything else in the file.\n"
                "- Return ONLY the fixed .lean file content."
            )),
            HumanMessage(content=f"Compilation errors:\n{prev_errors[-2000:]}\n\nCurrent file:\n{content}"),
        ]

    try:
        response = model.invoke(messages)
        new_content = _extract_lean_code(str(response.content))
        if len(new_content) < 10:
            print(f"[prover] ⚠ 响应太短: {new_content[:50]}")
            return None
        return new_content
    except Exception as e:
        print(f"[prover] ⚠ LLM 调用失败: {e}")
        return None


def run_prover_node(state: ArchonState) -> ArchonState:
    """≡ prover agent — 通过 DeerFlow 模型通道填充 sorry"""
    ws = state["workspace_path"]
    stage = state["current_stage"]
    tasks = state.get("pending_tasks", [])

    if not tasks:
        print(f"[prover] 没有待办任务")
        state["next_action"] = "review"
        return state

    print(f"[prover] 开始证明阶段 (stage={stage})")

    MAX_RETRIES = 3

    for task in tasks:
        file_path = task.strip()
        if not file_path:
            continue

        abs_path = Path(ws) / file_path
        if not abs_path.exists() or abs_path.suffix != ".lean":
            continue

        # 检查是否还有 sorry
        if "sorry" not in abs_path.read_text():
            print(f"[prover] ⏭️  {file_path} 无剩余 sorry")
            continue

        print(f"[prover] 📝 {file_path} — 正在通过 DeerFlow 模型填充...")

        last_errors = ""
        for attempt in range(MAX_RETRIES):
            print(f"[prover]   └─ attempt {attempt + 1}/{MAX_RETRIES}")

            new_content = _call_llm_fill_sorry(file_path, ws, attempt, last_errors)
            if new_content is None:
                continue

            # 应用生成的内容
            abs_path.write_text(new_content)

            # 编译验证
            r = _run_bash("lake build 2>&1", ws)
            if r.returncode == 0:
                print(f"[prover] ✅ {file_path} — 证明成功")
                _write_task_result(ws, file_path, "RESOLVED")
                break
            else:
                last_errors = (r.stderr or "") + (r.stdout or "")
                # 截断到合理长度
                last_errors = last_errors[-3000:]
                print(f"[prover]   └─ ❌ 编译失败 (attempt {attempt + 1})")
                print(f"[prover]   └─ 错误: {last_errors[:200]}...")
        else:
            # 所有重试都失败
            print(f"[prover] ❌ {file_path} — 所有尝试失败")
            _write_task_result(ws, file_path, "FAILED", errors=last_errors)

    state["next_action"] = "review"
    print(f"[prover] 阶段完成")
    return state


def run_review_node(state: ArchonState) -> ArchonState:
    """≡ review agent — 审查结果、更新进度"""
    ws = state["workspace_path"]
    state["loop_count"] = state.get("loop_count", 0) + 1
    print(f"[review] 开始审查 (loop #{state['loop_count']})")

    # 运行 lake build 验证
    print(f"[review] 运行 lake build...")
    r = _run_bash("lake build 2>&1", ws)
    build_ok = r.returncode == 0
    sorry_count = _count_sorries(ws)

    # 生成 session 记录
    sessions_dir = _state_dir(ws) / "proof-journal" / "sessions"
    existing = list(sessions_dir.glob("session_*"))
    session_num = len(existing) + 1
    session_dir = sessions_dir / f"session_{session_num}"
    session_dir.mkdir(parents=True, exist_ok=True)

    # milestones.jsonl
    _write_file(
        session_dir / "milestones.jsonl",
        json.dumps(
            {
                "ts": str(subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True).stdout.strip()),
                "event": "review_session",
                "session": session_num,
                "build_ok": build_ok,
                "remaining_sorries": sorry_count,
                "loop_count": state["loop_count"],
            }
        )
        + "\n",
    )

    # summary.md
    _write_file(
        session_dir / "summary.md",
        f"# Session {session_num} Summary\n\n"
        f"- Build: {'✅ PASS' if build_ok else '❌ FAIL'}\n"
        f"- Remaining sorries: {sorry_count}\n"
        f"- Loop count: {state['loop_count']}\n",
    )

    # recommendations.md
    if sorry_count == 0:
        _write_file(
            session_dir / "recommendations.md",
            "# Recommendations\n\n🎉 所有 sorry 已解决！项目可编译通过。\n",
        )
        _write_file(
            _state_dir(ws) / "PROJECT_STATUS.md",
            f"# Project Status\n\n✅ **COMPLETE** — Build: {'PASS' if build_ok else 'FAIL'}, Sorries: {sorry_count}\n",
        )
        state["current_stage"] = "COMPLETE"
        state["next_action"] = "end"
    else:
        _write_file(
            session_dir / "recommendations.md",
            f"# Recommendations\n\n"
            f"仍有 {sorry_count} 个 sorry 待解决。\n"
            f"Build: {'PASS' if build_ok else 'FAIL'}\n"
            f"建议 plan agent 重新评估剩余任务。\n",
        )
        _write_file(
            _state_dir(ws) / "PROJECT_STATUS.md",
            f"# Project Status\n\n"
            f"🔄 In Progress — Loop #{state['loop_count']}\n"
            f"Build: {'PASS' if build_ok else 'FAIL'}\n"
            f"Sorries: {sorry_count}\n",
        )
        state["next_action"] = "plan"

    print(f"[review] 审查完成 (build={'✅' if build_ok else '❌'}, sorries={sorry_count})")
    return state


# ═══════════════════════════════════════════════════════════════════════
# 路由函数
# ═══════════════════════════════════════════════════════════════════════


def route_after_review(state: ArchonState) -> str:
    """条件路由：完成或继续循环"""
    max_loops = state.get("max_loops", 10)
    loop_count = state.get("loop_count", 0)

    if state.get("current_stage") == "COMPLETE" or state.get("next_action") == "end":
        print(f"[route] ✅ 项目完成，终止")
        return END

    if loop_count >= max_loops:
        print(f"[route] ⚠ 达到最大循环次数 ({max_loops})，终止")
        state["current_stage"] = "ERROR"
        return END

    print(f"[route] 🔄 继续循环 (loop {loop_count}/{max_loops})")
    return "plan"


# ═══════════════════════════════════════════════════════════════════════
# 构建与编译图
# ═══════════════════════════════════════════════════════════════════════


def build_archon_graph() -> StateGraph:
    """构建 Archon LangGraph 工作流"""

    workflow = StateGraph(ArchonState)

    # 添加节点
    workflow.add_node("init", run_init_node)
    workflow.add_node("plan", run_plan_node)
    workflow.add_node("prover", run_prover_node)
    workflow.add_node("review", run_review_node)

    # 设置入口
    workflow.set_entry_point("init")

    # 普通边
    workflow.add_edge("init", "plan")
    workflow.add_edge("plan", "prover")
    workflow.add_edge("prover", "review")

    # 条件路由边 — 核心循环
    workflow.add_conditional_edges(
        "review",
        route_after_review,
        {"plan": "plan", END: END},
    )

    # 编译
    app = workflow.compile(checkpointer=MemorySaver())
    return app


# ═══════════════════════════════════════════════════════════════════════
# 入口函数 — 供 DeerFlow Gateway 调用
# ═══════════════════════════════════════════════════════════════════════


def run_archon_workflow(
    workspace_path: str, max_loops: int = 10
) -> dict:
    """运行完整的 Archon 工作流。

    Args:
        workspace_path: Lean 项目的沙箱绝对路径
        max_loops: 最大迭代次数

    Returns:
        最终状态字典
    """
    app = build_archon_graph()

    initial_state: ArchonState = {
        "workspace_path": workspace_path,
        "current_stage": "INIT",
        "pending_tasks": [],
        "max_loops": max_loops,
        "loop_count": 0,
        "next_action": "init",
    }

    config = {"configurable": {"thread_id": f"archon-{Path(workspace_path).name}"}}
    final_state = app.invoke(initial_state, config=config)
    return final_state


if __name__ == "__main__":
    # 测试：在工作目录上运行
    import sys

    ws = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(f"Running Archon workflow on: {ws}")
    result = run_archon_workflow(ws)
    print(f"\nFinal state: stage={result['current_stage']}, loop_count={result['loop_count']}")
