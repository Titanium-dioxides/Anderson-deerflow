from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / "overlay" / "backend" / "workflows"


def _install_dependency_stubs() -> None:
    langchain_core = types.ModuleType("langchain_core")
    langchain_messages = types.ModuleType("langchain_core.messages")

    class HumanMessage:
        def __init__(self, content: str):
            self.content = content

    langchain_messages.HumanMessage = HumanMessage
    langchain_core.messages = langchain_messages
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.messages"] = langchain_messages

    langgraph = types.ModuleType("langgraph")
    langgraph_graph = types.ModuleType("langgraph.graph")
    langgraph_graph_message = types.ModuleType("langgraph.graph.message")

    class StateGraph:
        def __init__(self, *_args, **_kwargs):
            return None

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def set_finish_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def add_conditional_edges(self, *_args, **_kwargs):
            return None

        def compile(self, **_kwargs):
            return self

    langgraph_graph.END = "__END__"
    langgraph_graph.StateGraph = StateGraph
    langgraph_graph_message.add_messages = lambda _existing, new: new
    langgraph.graph = langgraph_graph
    sys.modules["langgraph"] = langgraph
    sys.modules["langgraph.graph"] = langgraph_graph
    sys.modules["langgraph.graph.message"] = langgraph_graph_message


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_phase_modules():
    _install_dependency_stubs()

    workflow_pkg = types.ModuleType("phase4_testpkg")
    workflow_pkg.__path__ = [str(WORKFLOWS_DIR)]
    sys.modules["phase4_testpkg"] = workflow_pkg

    phase1 = _load_module("phase4_testpkg.phase1_runtime", WORKFLOWS_DIR / "phase1_runtime.py")
    phase3 = _load_module("phase4_testpkg.phase3_archon_scaffolding", WORKFLOWS_DIR / "phase3_archon_scaffolding.py")
    phase4 = _load_module("phase4_testpkg.phase4_archon_proving", WORKFLOWS_DIR / "phase4_archon_proving.py")
    return phase1, phase3, phase4


def _base_state(thread_id: str, project_name: str, statement: str, max_loops: int = 3) -> dict:
    return {
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
        "loop_count": 0,
        "max_loops": max_loops,
        "parallelism": 2,
        "artifacts": [],
    }


def _prepare_phase3_workspace(project_root: Path, statement: str) -> None:
    (project_root / ".archon" / "task_results").mkdir(parents=True, exist_ok=True)
    (project_root / ".archon" / "proof-journal" / "sessions").mkdir(parents=True, exist_ok=True)
    (project_root / "formal" / "src" / "Topology").mkdir(parents=True, exist_ok=True)
    (project_root / "memory" / "archon").mkdir(parents=True, exist_ok=True)
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    (project_root / "formal" / "src" / "Topology" / "Main.lean").write_text("import Mathlib\n\ntheorem top_main : True := by\n  sorry\n")
    (project_root / "formal" / "src" / "Topology" / "Helpers.lean").write_text("import Mathlib\n\nlemma top_helper : True := by\n  sorry\n")
    (project_root / ".archon" / "task_pending.md").write_text(
        "# Index\n\n- [ ] formal/src/Topology/Main.lean (autoformalize: skeleton with sorries)\n- [ ] formal/src/Topology/Helpers.lean (autoformalize: skeleton with sorries)\n"
    )
    (project_root / ".archon" / "PROJECT_STATUS.md").write_text("# Project Status\n")
    (project_root / "manifests" / "phase3_archon_scaffolding.json").write_text(
        json.dumps(
            {
                "phase": "phase3_archon_scaffolding",
                "statement": statement,
                "lean_project_root": "formal",
                "archon_state_root": ".archon",
                "references_index_path": "demo/references/structured/phase3_reference_index.json",
                "module_files": [
                    "formal/src/Topology/Main.lean",
                    "formal/src/Topology/Helpers.lean",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def test_phase4_proving_loop_records_attempts_and_completes(tmp_path, monkeypatch):
    phase1, _phase3, phase4 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))
    attempt_counts = {"formal/src/Topology/Main.lean": 0, "formal/src/Topology/Helpers.lean": 0}

    def fake_run(prompt: str, *, system_prompt: str, tools=None, thread_id: str) -> str:
        if "plan agent" in system_prompt:
            if "Topology/Helpers.lean" in prompt and "failure_mode" in prompt:
                return json.dumps(
                    {
                        "focus_files": ["formal/src/Topology/Helpers.lean"],
                        "strategy": "Retry helper with the reviewer guidance.",
                        "rationale": "Only helper remains pending.",
                        "stop_files": [],
                    }
                )
            return json.dumps(
                {
                    "focus_files": ["formal/src/Topology/Main.lean", "formal/src/Topology/Helpers.lean"],
                    "strategy": "Clear the main theorem first, then helper.",
                    "rationale": "Both files are pending.",
                    "stop_files": [],
                }
            )
        if "lean agent" in system_prompt:
            target = prompt.split("Target file:\n", 1)[1].split("\n\n", 1)[0]
            attempt_counts[target] += 1
            if target.endswith("Main.lean"):
                return json.dumps(
                    {
                        "status": "completed",
                        "updated_content": "import Mathlib\n\ntheorem top_main : True := by\n  trivial\n",
                        "summary": "Closed the main theorem.",
                        "failure_mode": "",
                    }
                )
            if attempt_counts[target] == 1:
                return json.dumps(
                    {
                        "status": "needs_retry",
                        "updated_content": "import Mathlib\n\nlemma top_helper : True := by\n  sorry\n",
                        "summary": "Helper still needs a direct proof.",
                        "failure_mode": "missing_lemma_route",
                    }
                )
            return json.dumps(
                {
                    "status": "completed",
                    "updated_content": "import Mathlib\n\nlemma top_helper : True := by\n  trivial\n",
                    "summary": "Closed the helper theorem.",
                    "failure_mode": "",
                }
            )
        if "review agent" in system_prompt:
            continue_loop = "formal/src/Topology/Helpers.lean" in prompt
            return json.dumps(
                {
                    "global_strategy": "Avoid repeating the same helper dead end.",
                    "blockers": ["missing_lemma_route"] if continue_loop else [],
                    "continue_loop": continue_loop,
                    "dead_end_files": [],
                }
            )
        raise AssertionError(f"Unexpected prompt: {system_prompt}")

    monkeypatch.setattr(phase4, "_run_deerflow_agent", fake_run)

    state = _base_state("thread-phase4", "demo", "Prove True.", max_loops=3)
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_phase3_workspace(project_root, state["statement"])

    state = phase4.phase3_sync_node(state)
    state = phase4.plan_agent_node(state)
    state = phase4.lean_agents_node(state)
    state = phase4.reviewer_node(state)
    state = phase4.review_agent_node(state)
    assert state["stage"] == "STRATEGY_READY"

    state = phase4.plan_agent_node(state)
    state = phase4.lean_agents_node(state)
    state = phase4.reviewer_node(state)
    state = phase4.review_agent_node(state)

    assert state["stage"] == "COMPLETE"
    assert sorted(state["completed"]) == ["formal/src/Topology/Helpers.lean", "formal/src/Topology/Main.lean"]
    assert state["pending"] == []
    assert len(state["attempt_history"]) == 3
    assert len(state["failure_modes"]) == 1
    assert len(state["review_history"]) == 2
    assert (project_root / "memory" / "archon" / "attempt_history.jsonl").exists()
    assert json.loads((project_root / "manifests" / "phase4_archon_proving.json").read_text())["stage"] == "COMPLETE"


def test_phase4_proving_loop_fails_after_repeated_dead_end(tmp_path, monkeypatch):
    phase1, _phase3, phase4 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    def fake_run(prompt: str, *, system_prompt: str, tools=None, thread_id: str) -> str:
        if "plan agent" in system_prompt:
            return json.dumps(
                {
                    "focus_files": ["formal/src/Topology/Main.lean"],
                    "strategy": "Keep trying the blocked file.",
                    "rationale": "Only one file remains.",
                    "stop_files": [],
                }
            )
        if "lean agent" in system_prompt:
            return json.dumps(
                {
                    "status": "blocked",
                    "updated_content": "import Mathlib\n\ntheorem top_main : True := by\n  sorry\n",
                    "summary": "Still blocked on the same route.",
                    "failure_mode": "same_dead_end",
                }
            )
        if "review agent" in system_prompt:
            return json.dumps(
                {
                    "global_strategy": "This route is stalled.",
                    "blockers": ["same_dead_end"],
                    "continue_loop": True,
                    "dead_end_files": ["formal/src/Topology/Main.lean"],
                }
            )
        raise AssertionError(f"Unexpected prompt: {system_prompt}")

    monkeypatch.setattr(phase4, "_run_deerflow_agent", fake_run)

    state = _base_state("thread-phase4-fail", "demo", "Prove True.", max_loops=2)
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_phase3_workspace(project_root, state["statement"])
    (project_root / "formal" / "src" / "Topology" / "Helpers.lean").write_text("import Mathlib\n\nlemma top_helper : True := by\n  trivial\n")

    state = phase4.phase3_sync_node(state)
    state = phase4.plan_agent_node(state)
    state = phase4.lean_agents_node(state)
    state = phase4.reviewer_node(state)
    state = phase4.review_agent_node(state)
    assert state["stage"] == "STRATEGY_READY"

    state = phase4.plan_agent_node(state)
    state = phase4.lean_agents_node(state)
    state = phase4.reviewer_node(state)
    state = phase4.review_agent_node(state)

    assert state["stage"] == "FAILED"
    assert state["pending"] == ["formal/src/Topology/Main.lean"]
    assert len(state["failure_modes"]) == 2
    assert len(state["review_history"]) == 2
    manifest = json.loads((project_root / "manifests" / "phase4_archon_proving.json").read_text())
    assert manifest["stage"] == "FAILED"


def test_phase4_lean_agent_prefers_task_subagent_runtime(tmp_path, monkeypatch):
    phase1, _phase3, phase4 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    class FakeTaskTool:
        name = "task"

        def __init__(self):
            self.calls = []

        def invoke(self, payload):
            self.calls.append(payload)
            return json.dumps(
                {
                    "status": "completed",
                    "updated_content": "import Mathlib\n\ntheorem top_main : True := by\n  trivial\n",
                    "summary": "Solved through subagent task runtime.",
                    "failure_mode": "",
                }
            )

    task_tool = FakeTaskTool()
    monkeypatch.setattr(phase4, "_find_task_tool", lambda: task_tool)
    monkeypatch.setattr(
        phase4,
        "_run_deerflow_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct fallback should not be used")),
    )

    state = _base_state("thread-phase4-task", "demo", "Prove True.", max_loops=1)
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_phase3_workspace(project_root, state["statement"])
    (project_root / "formal" / "src" / "Topology" / "Helpers.lean").write_text("import Mathlib\n\nlemma top_helper : True := by\n  trivial\n")

    state = phase4.phase3_sync_node(state)
    state["current_plan"] = {
        "loop_count": 0,
        "focus_files": ["formal/src/Topology/Main.lean"],
        "strategy": "Use subagent runtime.",
        "rationale": "Verify task tool path.",
        "stop_files": [],
    }
    state = phase4.lean_agents_node(state)

    assert state["completed"] == ["formal/src/Topology/Helpers.lean", "formal/src/Topology/Main.lean"]
    assert state["pending"] == []
    assert state["attempt_history"][0]["execution_mode"] == "subagent_task"
    assert task_tool.calls[0]["subagent_type"] == "general-purpose"
