"""
Phase 4 — Archon Proving Loop (DeerFlow-native).

Builds the paper-aligned proving loop on top of the Phase 3 scaffold:
  - sync scaffolded Lean files and Archon state
  - plan-agent strategy generation
  - per-file lean-agent proving attempts
  - reviewer state reduction
  - review-agent cross-session strategy updates
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from .phase1_runtime import (
    _memory_checkpointer,
    _runtime_root,
    bootstrap_layout,
    log_runtime_event,
    merge_artifacts,
)
from .phase3_archon_scaffolding import _extract_json_object, _run_deerflow_agent


class Phase4ArchonProvingState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    project_name: str
    statement: str
    stage: Literal[
        "BOOTSTRAP",
        "PHASE3_SYNC",
        "PLAN_READY",
        "PROVING",
        "REVIEWED",
        "STRATEGY_READY",
        "COMPLETE",
        "FAILED",
    ]
    workspace_root: str
    uploads_root: str
    outputs_root: str
    project_root: str
    references_root: str
    informal_root: str
    formal_root: str
    memory_root: str
    journal_root: str
    manifests_root: str
    scratch_root: str
    archon_state_root: str
    lean_project_root: str
    references_index_path: str
    module_files: list[str]
    pending: list[str]
    completed: list[str]
    failure_modes: list[dict]
    attempt_history: list[dict]
    review_history: list[dict]
    current_plan: dict
    review_summary: dict
    blocked_files: list[str]
    lean_subagent_type: str
    lean_tool_profile: str
    loop_count: int
    max_loops: int
    parallelism: int
    artifacts: Annotated[list[str], merge_artifacts]


def _host_project_root(thread_id: str, project_name: str) -> Path:
    return _runtime_root() / "threads" / thread_id / "user-data" / "workspace" / project_name


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _read_text(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def _get_available_tools():
    import_candidates = [
        ("deerflow.tools", "get_available_tools"),
        ("deerflow.tools.registry", "get_available_tools"),
        ("deerflow.agent.tools", "get_available_tools"),
    ]
    for module_name, attr_name in import_candidates:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            return getattr(module, attr_name)
        except Exception:
            continue
    return None


def _find_task_tool() -> object | None:
    get_available_tools = _get_available_tools()
    if get_available_tools is None:
        return None
    try:
        tools = get_available_tools(
            groups=[],
            include_mcp=False,
            model_name="",
            subagent_enabled=True,
        )
    except TypeError:
        try:
            tools = get_available_tools(subagent_enabled=True)
        except Exception:
            return None
    except Exception:
        return None

    for tool in tools or []:
        if getattr(tool, "name", "") == "task":
            return tool
    return None


def _get_available_tools_for_groups(*, groups: list[str], include_mcp: bool = True, subagent_enabled: bool = False):
    get_available_tools = _get_available_tools()
    if get_available_tools is None:
        return None
    try:
        return get_available_tools(
            groups=groups,
            include_mcp=include_mcp,
            model_name="",
            subagent_enabled=subagent_enabled,
        )
    except TypeError:
        try:
            return get_available_tools(groups=groups)
        except Exception:
            return None
    except Exception:
        return None


def _invoke_task_tool(task_tool, *, description: str, prompt: str, subagent_type: str) -> str:
    payload = {
        "description": description,
        "prompt": prompt,
        "subagent_type": subagent_type,
    }
    if hasattr(task_tool, "invoke"):
        result = task_tool.invoke(payload)
    else:
        result = task_tool(**payload)
    return str(result)


def _run_lean_subagent(
    prompt: str,
    *,
    system_prompt: str,
    thread_id: str,
    description: str,
    subagent_type: str,
) -> tuple[str, str]:
    task_tool = _find_task_tool()
    if task_tool is not None:
        task_prompt = (
            f"System instructions:\n{system_prompt}\n\n"
            f"User task:\n{prompt}\n\n"
            "Return only the requested JSON."
        )
        try:
            return _invoke_task_tool(
                task_tool,
                description=description,
                prompt=task_prompt,
                subagent_type=subagent_type,
            ), "subagent_task"
        except Exception:
            pass
    lean_tools = _get_lean_tools()
    return _run_deerflow_agent(
        prompt,
        system_prompt=system_prompt,
        tools=lean_tools,
        thread_id=thread_id,
    ), "direct_agent_fallback"


def _effective_focus_files(
    pending: list[str],
    requested: list[str],
    blocked_files: list[str],
    stop_files: list[str],
    parallelism: int,
) -> list[str]:
    filtered_pending = [item for item in pending if item not in blocked_files and item not in stop_files]
    filtered_requested = [item for item in requested if item in filtered_pending]
    if filtered_requested:
        return filtered_requested[: max(1, parallelism)]
    return filtered_pending[: max(1, parallelism)]


def _get_lean_tools():
    """Prefer DeerFlow tool aggregation; fall back to local overlay tools."""
    aggregated = _get_available_tools_for_groups(
        groups=["lean"],
        include_mcp=True,
        subagent_enabled=False,
    )
    if aggregated:
        return aggregated
    try:
        from overlay.backend.mcp.lean_tools import LEAN_TOOLS
        return LEAN_TOOLS
    except Exception:
        return []


def _lean_agent_system_prompt(tool_profile: str) -> str:
    return (
        "You are the Archon lean agent.\n"
        "Work on one Lean file. Return JSON with keys: status, updated_content, summary, failure_mode.\n"
        "status must be one of completed, needs_retry, blocked.\n"
        f"Tool profile: {tool_profile}.\n"
        "Use available Lean tools (lean_check_file, lean_file_outline, lean_sorry_scan, "
        "lean_theorem_search, lean_goal_at, lean_build) to inspect and fix the file.\n"
        "After fixing, run lean_check_file to verify there are no errors."
    )


def _relative_formal_path(project_root: Path, file_path: Path) -> str:
    return str(file_path.relative_to(project_root))


def _scan_pending_from_files(project_root: Path, module_files: list[str]) -> tuple[list[str], list[str]]:
    pending: list[str] = []
    completed: list[str] = []
    for module_file in module_files:
        content = _read_text(project_root / module_file)
        if "sorry" in content:
            pending.append(module_file)
        else:
            completed.append(module_file)
    return pending, completed


def _session_dir(project_root: Path, loop_count: int) -> Path:
    return project_root / ".archon" / "proof-journal" / "sessions" / f"session_{loop_count:03d}"


def phase3_sync_node(state: Phase4ArchonProvingState) -> Phase4ArchonProvingState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    manifest_path = project_root / "manifests" / "phase3_archon_scaffolding.json"
    manifest = _load_json(manifest_path, {})

    module_files = manifest.get("module_files") or []
    if not module_files:
        module_files = [
            _relative_formal_path(project_root, file_path)
            for file_path in sorted((project_root / "formal" / "src").rglob("*.lean"))
        ]
    pending, completed = _scan_pending_from_files(project_root, module_files)

    sync_manifest = {
        "phase": "phase4_archon_proving",
        "module_files": module_files,
        "pending": pending,
        "completed": completed,
        "loop_count": state.get("loop_count", 0),
    }
    sync_manifest_path = project_root / "manifests" / "phase4_sync.json"
    sync_manifest_path.write_text(json.dumps(sync_manifest, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase4_archon_proving",
        "phase3_sync",
        {
            "module_files": module_files,
            "pending_count": len(pending),
            "completed_count": len(completed),
        },
    )

    return {
        **state,
        "stage": "PHASE3_SYNC",
        "statement": state.get("statement") or manifest.get("statement", ""),
        "archon_state_root": state.get("archon_state_root") or manifest.get("archon_state_root", ".archon"),
        "lean_project_root": state.get("lean_project_root") or manifest.get("lean_project_root", "formal"),
        "references_index_path": state.get("references_index_path") or manifest.get("references_index_path", ""),
        "module_files": module_files,
        "pending": pending,
        "completed": completed,
        "artifacts": [f"{project_name}/manifests/phase4_sync.json"],
    }


def plan_agent_node(state: Phase4ArchonProvingState) -> Phase4ArchonProvingState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    pending = state.get("pending", [])
    completed = state.get("completed", [])
    failure_modes = state.get("failure_modes", [])
    previous_review = state.get("review_history", [])[-1] if state.get("review_history") else {}
    blocked_files = state.get("blocked_files", [])
    loop_count = state.get("loop_count", 0)

    system_prompt = (
        "You are the Archon plan agent.\n"
        "Read the proving state and produce the next targeted proving plan.\n"
        "Return compact JSON with keys: focus_files, strategy, rationale, stop_files."
    )
    prompt = (
        f"Statement:\n{state.get('statement', '')}\n\n"
        f"Pending files:\n{json.dumps(pending, ensure_ascii=False)}\n\n"
        f"Completed files:\n{json.dumps(completed, ensure_ascii=False)}\n\n"
        f"Failure modes:\n{json.dumps(failure_modes[-8:], ensure_ascii=False)}\n\n"
        f"Previous review:\n{json.dumps(previous_review, ensure_ascii=False)}\n\n"
        "Prioritize progress, avoid repeated dead ends, and return JSON only."
    )

    raw_plan = _run_deerflow_agent(
        prompt,
        system_prompt=system_prompt,
        tools=[],
        thread_id=f"{thread_id}-archon-plan-{loop_count}",
    )
    try:
        parsed = _extract_json_object(raw_plan)
    except Exception:
        parsed = {
            "focus_files": pending[: max(1, min(len(pending), state.get("parallelism", 2)))],
            "strategy": "Fallback strategy: work pending files in order and avoid repeated failures.",
            "rationale": "Plan output could not be parsed.",
            "stop_files": [],
        }

    stop_files = [file for file in parsed.get("stop_files", []) if file in pending]
    focus_files = _effective_focus_files(
        pending,
        parsed.get("focus_files", []),
        blocked_files,
        stop_files,
        state.get("parallelism", 2),
    )
    if stop_files:
        focus_files = _effective_focus_files(
            pending,
            focus_files,
            blocked_files,
            stop_files,
            state.get("parallelism", 2),
        )

    current_plan = {
        "loop_count": loop_count,
        "focus_files": focus_files,
        "strategy": parsed.get("strategy", ""),
        "rationale": parsed.get("rationale", ""),
        "stop_files": stop_files,
        "blocked_files": blocked_files,
    }

    session_dir = _session_dir(project_root, loop_count)
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "plan.json").write_text(json.dumps(current_plan, ensure_ascii=False, indent=2))
    (project_root / ".archon" / "CURRENT_PLAN.md").write_text(
        "# Current Plan\n\n"
        f"- Loop: {loop_count}\n"
        f"- Strategy: {current_plan['strategy']}\n"
        f"- Focus files: {', '.join(focus_files) if focus_files else '(none)'}\n"
        f"- Blocked files: {', '.join(blocked_files) if blocked_files else '(none)'}\n"
        f"- Stop files: {', '.join(stop_files) if stop_files else '(none)'}\n"
        f"- Rationale: {current_plan['rationale']}\n"
    )
    log_runtime_event(
        thread_id,
        "phase4_archon_proving",
        "plan_agent",
        {
            "loop_count": loop_count,
            "focus_files": focus_files,
            "blocked_files": blocked_files,
            "stop_files": stop_files,
        },
    )

    return {
        **state,
        "stage": "PLAN_READY",
        "current_plan": current_plan,
        "artifacts": [
            f"{project_name}/.archon/CURRENT_PLAN.md",
            f"{project_name}/.archon/proof-journal/sessions/session_{loop_count:03d}/plan.json",
        ],
    }


def lean_agents_node(state: Phase4ArchonProvingState) -> Phase4ArchonProvingState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    current_plan = state.get("current_plan", {})
    focus_files = current_plan.get("focus_files", [])
    loop_count = state.get("loop_count", 0)

    updated_completed = list(state.get("completed", []))
    updated_pending = list(state.get("pending", []))
    updated_attempt_history = list(state.get("attempt_history", []))
    updated_failure_modes = list(state.get("failure_modes", []))
    artifacts: list[str] = []

    def run_single_file(module_file: str) -> tuple[dict, str]:
        module_path = project_root / module_file
        before_content = _read_text(module_path)
        system_prompt = _lean_agent_system_prompt(state.get("lean_tool_profile", "lean-lsp-reference-files"))
        prompt = (
            f"Statement:\n{state.get('statement', '')}\n\n"
            f"Strategy:\n{current_plan.get('strategy', '')}\n\n"
            f"Tool profile:\n{state.get('lean_tool_profile', 'lean-lsp-reference-files')}\n\n"
            f"Target file:\n{module_file}\n\n"
            f"Current content:\n{before_content}\n\n"
            "Return JSON only."
        )

        raw_attempt, execution_mode = _run_lean_subagent(
            prompt,
            system_prompt=system_prompt,
            thread_id=f"{thread_id}-archon-lean-{loop_count}-{Path(module_file).stem}",
            description=f"Formalize {module_file}",
            subagent_type=state.get("lean_subagent_type", "general-purpose"),
        )
        try:
            parsed = _extract_json_object(raw_attempt)
        except Exception:
            parsed = {
                "status": "needs_retry",
                "updated_content": before_content,
                "summary": "Lean agent output could not be parsed.",
                "failure_mode": "unparseable_output",
            }
        parsed["_execution_mode"] = execution_mode
        return parsed, before_content

    # DeerFlow-native priority: use task/subagent orchestration per file and collect
    # results in the parent workflow, rather than layering a parallel thread pool here.
    results = [(module_file, *run_single_file(module_file)) for module_file in focus_files]

    for module_file, parsed, before_content in results:
        module_path = project_root / module_file

        updated_content = parsed.get("updated_content", before_content) or before_content
        module_path.write_text(updated_content)
        after_has_sorry = "sorry" in updated_content
        status = parsed.get("status", "needs_retry")
        if not after_has_sorry:
            status = "completed"

        attempt_record = {
            "loop_count": loop_count,
            "file": module_file,
            "status": status,
            "summary": parsed.get("summary", ""),
            "failure_mode": parsed.get("failure_mode", ""),
            "execution_mode": parsed.get("_execution_mode", "unknown"),
            "tool_profile": state.get("lean_tool_profile", "lean-lsp-reference-files"),
        }
        updated_attempt_history.append(attempt_record)

        result_path = project_root / ".archon" / "task_results" / f"{Path(module_file).stem}.md"
        result_path.write_text(
            f"# Result for {module_file}\n\n"
            f"- Loop: {loop_count}\n"
            f"- Status: {status}\n"
            f"- Execution mode: {parsed.get('_execution_mode', 'unknown')}\n"
            f"- Summary: {parsed.get('summary', '')}\n"
            f"- Failure mode: {parsed.get('failure_mode', '')}\n"
        )

        if status == "completed":
            if module_file not in updated_completed:
                updated_completed.append(module_file)
            updated_pending = [item for item in updated_pending if item != module_file]
        else:
            failure_mode = parsed.get("failure_mode") or "needs_retry"
            updated_failure_modes.append(
                {
                    "loop_count": loop_count,
                    "file": module_file,
                    "failure_mode": failure_mode,
                    "summary": parsed.get("summary", ""),
                }
            )
            if module_file not in updated_pending and after_has_sorry:
                updated_pending.append(module_file)
            if module_file in updated_completed and after_has_sorry:
                updated_completed = [item for item in updated_completed if item != module_file]

        _append_jsonl(project_root / "memory" / "archon" / "attempt_history.jsonl", attempt_record)
        artifacts.append(f"{project_name}/.archon/task_results/{Path(module_file).stem}.md")
        artifacts.append(f"{project_name}/{module_file}")
        log_runtime_event(
            thread_id,
            "phase4_archon_proving",
            "lean_agent_attempt",
            {
                "loop_count": loop_count,
                "file": module_file,
                "status": status,
                "execution_mode": parsed.get("_execution_mode", "unknown"),
                "failure_mode": parsed.get("failure_mode", ""),
            },
        )

    return {
        **state,
        "stage": "PROVING",
        "completed": updated_completed,
        "pending": updated_pending,
        "attempt_history": updated_attempt_history,
        "failure_modes": updated_failure_modes,
        "artifacts": artifacts + [f"{project_name}/memory/archon/attempt_history.jsonl"],
    }


def reviewer_node(state: Phase4ArchonProvingState) -> Phase4ArchonProvingState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    loop_count = state.get("loop_count", 0)

    failure_counter = Counter(item.get("failure_mode", "unknown") for item in state.get("failure_modes", []))
    per_file_failures = Counter(item.get("file", "") for item in state.get("failure_modes", []))
    stalled_files = [file for file, count in per_file_failures.items() if count >= 2 and file in state.get("pending", [])]
    progress_made = any(item.get("loop_count") == loop_count and item.get("status") == "completed" for item in state.get("attempt_history", []))

    review_summary = {
        "loop_count": loop_count,
        "pending": state.get("pending", []),
        "completed": state.get("completed", []),
        "stalled_files": stalled_files,
        "progress_made": progress_made,
        "failure_counter": dict(failure_counter),
    }

    session_dir = _session_dir(project_root, loop_count)
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "reviewer.json").write_text(json.dumps(review_summary, ensure_ascii=False, indent=2))
    (project_root / ".archon" / "PROJECT_STATUS.md").write_text(
        "# Project Status\n\n"
        f"- Loop: {loop_count}\n"
        f"- Pending: {len(review_summary['pending'])}\n"
        f"- Completed: {len(review_summary['completed'])}\n"
        f"- Progress made: {'yes' if progress_made else 'no'}\n"
        f"- Stalled files: {', '.join(stalled_files) if stalled_files else '(none)'}\n"
    )
    (project_root / ".archon" / "REVIEW_GUIDANCE.md").write_text(
        "# Review Guidance\n\n"
        f"- Loop: {loop_count}\n"
        f"- Progress made: {'yes' if progress_made else 'no'}\n"
        f"- Stalled files: {', '.join(stalled_files) if stalled_files else '(none)'}\n"
        f"- Failure counts: {json.dumps(review_summary['failure_counter'], ensure_ascii=False)}\n"
    )
    log_runtime_event(
        thread_id,
        "phase4_archon_proving",
        "reviewer",
        {
            "loop_count": loop_count,
            "progress_made": progress_made,
            "stalled_files": stalled_files,
        },
    )

    return {
        **state,
        "stage": "REVIEWED",
        "review_summary": review_summary,
        "artifacts": [
            f"{project_name}/.archon/PROJECT_STATUS.md",
            f"{project_name}/.archon/REVIEW_GUIDANCE.md",
            f"{project_name}/.archon/proof-journal/sessions/session_{loop_count:03d}/reviewer.json",
        ],
    }


def review_agent_node(state: Phase4ArchonProvingState) -> Phase4ArchonProvingState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    loop_count = state.get("loop_count", 0)

    system_prompt = (
        "You are the Archon review agent.\n"
        "Analyze recent sessions and produce strategy guidance for the next plan agent.\n"
        "Return JSON with keys: global_strategy, blockers, continue_loop, dead_end_files."
    )
    prompt = (
        f"Current review summary:\n{json.dumps(state.get('review_summary', {}), ensure_ascii=False)}\n\n"
        f"Recent attempt history:\n{json.dumps(state.get('attempt_history', [])[-10:], ensure_ascii=False)}\n\n"
        "Return JSON only."
    )

    raw_review = _run_deerflow_agent(
        prompt,
        system_prompt=system_prompt,
        tools=[],
        thread_id=f"{thread_id}-archon-review-{loop_count}",
    )
    try:
        parsed = _extract_json_object(raw_review)
    except Exception:
        parsed = {
            "global_strategy": "Fallback review strategy: continue with remaining files and avoid repeated blockers.",
            "blockers": [],
            "continue_loop": bool(state.get("pending")),
            "dead_end_files": state.get("review_summary", {}).get("stalled_files", []),
        }

    review_record = {
        "loop_count": loop_count,
        "global_strategy": parsed.get("global_strategy", ""),
        "blockers": parsed.get("blockers", []),
        "continue_loop": parsed.get("continue_loop", bool(state.get("pending"))),
        "dead_end_files": parsed.get("dead_end_files", []),
    }
    updated_review_history = list(state.get("review_history", [])) + [review_record]
    updated_blocked_files = sorted(set(state.get("blocked_files", []) + review_record.get("dead_end_files", [])))

    _append_jsonl(project_root / "memory" / "archon" / "review_history.jsonl", review_record)
    session_dir = _session_dir(project_root, loop_count)
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "review_agent.json").write_text(json.dumps(review_record, ensure_ascii=False, indent=2))
    (project_root / "memory" / "archon" / "strategy.json").write_text(
        json.dumps(
            {
                "loop_count": loop_count,
                "global_strategy": review_record["global_strategy"],
                "blockers": review_record["blockers"],
                "blocked_files": updated_blocked_files,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    stage = "STRATEGY_READY"
    if not state.get("pending"):
        stage = "COMPLETE"
    elif loop_count + 1 >= state.get("max_loops", 3) and review_record.get("continue_loop", True):
        stage = "FAILED"

    final_manifest = {
        "phase": "phase4_archon_proving",
        "loop_count": loop_count + 1,
        "max_loops": state.get("max_loops", 3),
        "pending": state.get("pending", []),
        "completed": state.get("completed", []),
        "failure_modes": state.get("failure_modes", []),
        "review_record": review_record,
        "blocked_files": updated_blocked_files,
        "stage": stage,
    }
    (project_root / "manifests" / "phase4_archon_proving.json").write_text(json.dumps(final_manifest, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase4_archon_proving",
        "review_agent",
        {
            "loop_count": loop_count,
            "stage": stage,
            "pending": state.get("pending", []),
            "completed": state.get("completed", []),
            "blocked_files": updated_blocked_files,
        },
    )

    return {
        **state,
        "stage": stage,
        "review_history": updated_review_history,
        "blocked_files": updated_blocked_files,
        "loop_count": loop_count + 1,
        "artifacts": [
            f"{project_name}/memory/archon/review_history.jsonl",
            f"{project_name}/memory/archon/strategy.json",
            f"{project_name}/.archon/proof-journal/sessions/session_{loop_count:03d}/review_agent.json",
            f"{project_name}/manifests/phase4_archon_proving.json",
        ],
    }


def route_after_review(state: Phase4ArchonProvingState) -> str:
    if state.get("stage") in {"COMPLETE", "FAILED"}:
        return END
    return "plan_agent"


def build_phase4_archon_proving_graph():
    graph = StateGraph(Phase4ArchonProvingState)
    graph.add_node("bootstrap_layout", bootstrap_layout)
    graph.add_node("phase3_sync", phase3_sync_node)
    graph.add_node("plan_agent", plan_agent_node)
    graph.add_node("lean_agents", lean_agents_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("review_agent", review_agent_node)

    graph.set_entry_point("bootstrap_layout")
    graph.add_edge("bootstrap_layout", "phase3_sync")
    graph.add_edge("phase3_sync", "plan_agent")
    graph.add_edge("plan_agent", "lean_agents")
    graph.add_edge("lean_agents", "reviewer")
    graph.add_edge("reviewer", "review_agent")
    graph.add_conditional_edges("review_agent", route_after_review, {END: END, "plan_agent": "plan_agent"})
    return graph.compile(checkpointer=_memory_checkpointer())


def run_phase4_archon_proving_workflow(
    thread_id: str,
    statement: str = "",
    project_name: str = "project",
    max_loops: int = 3,
    parallelism: int = 2,
) -> dict:
    return build_phase4_archon_proving_graph().invoke(
        {
            "messages": [],
            "thread_id": thread_id,
            "project_name": project_name,
            "statement": statement,
            "stage": "BOOTSTRAP",
            "workspace_root": "",
            "uploads_root": "",
            "outputs_root": "",
            "project_root": "",
            "references_root": "",
            "informal_root": "",
            "formal_root": "",
            "memory_root": "",
            "journal_root": "",
            "manifests_root": "",
            "scratch_root": "",
            "archon_state_root": "",
            "lean_project_root": "",
            "references_index_path": "",
            "module_files": [],
            "pending": [],
            "completed": [],
            "failure_modes": [],
            "attempt_history": [],
            "review_history": [],
            "current_plan": {},
            "review_summary": {},
            "blocked_files": [],
            "lean_subagent_type": "general-purpose",
            "lean_tool_profile": "lean-lsp-reference-files",
            "loop_count": 0,
            "max_loops": max_loops,
            "parallelism": parallelism,
            "artifacts": [],
        },
        {"configurable": {"thread_id": thread_id}},
    )
