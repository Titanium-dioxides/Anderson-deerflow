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

    workflow_pkg = types.ModuleType("phase3_testpkg")
    workflow_pkg.__path__ = [str(WORKFLOWS_DIR)]
    sys.modules["phase3_testpkg"] = workflow_pkg

    phase1 = _load_module("phase3_testpkg.phase1_runtime", WORKFLOWS_DIR / "phase1_runtime.py")
    phase3 = _load_module("phase3_testpkg.phase3_archon_scaffolding", WORKFLOWS_DIR / "phase3_archon_scaffolding.py")
    return phase1, phase3


def _base_state(thread_id: str, project_name: str, statement: str) -> dict:
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
        "informal_proof_content": "",
        "candidate_proof_path": "",
        "archon_state_root": "",
        "lean_project_root": "",
        "references_index_path": "",
        "module_files": [],
        "sorry_count": 0,
        "artifact_manifest": {},
        "artifacts": [],
    }


def test_phase3_scaffold_generates_structured_archon_layout(tmp_path, monkeypatch):
    phase1, phase3 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(
        phase3,
        "_run_deerflow_agent",
        lambda *_args, **_kwargs: json.dumps(
            {
                "modules": [
                    {
                        "filename": "Topology/Main",
                        "content": "theorem generated_true : True := by\n  sorry\n",
                    },
                    {
                        "filename": "Topology/Helpers.lean",
                        "content": "lemma helper_true : True := by\n  sorry\n",
                    },
                ],
                "theorem_count": 2,
                "sorry_count": 2,
                "mathlib_deps": ["Mathlib"],
                "summary": "Main theorem plus helper lemma.",
            }
        ),
    )

    state = _base_state("thread-phase3", "demo-project", "Prove True.")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    (project_root / "informal" / "proofs" / "candidate_proof.md").write_text("An obvious proof.")
    (project_root / "references" / "raw" / "paper.md").write_text("# Reference")

    state = phase3.references_ingestion_node(state)
    state = phase3.project_init_node(state)
    state = phase3.autoformalize_node(state)
    state = phase3.module_split_node(state)
    state = phase3.manifest_node(state)

    assert (project_root / "references" / "structured" / "phase3_reference_index.json").exists()
    lakefile = (project_root / "formal" / "lakefile.lean").read_text()
    assert 'require mathlib from git' in lakefile
    assert 'srcDir := "src"' in lakefile
    assert (project_root / "formal" / "src" / "Topology" / "Main.lean").read_text().startswith("import Mathlib")
    assert (project_root / "formal" / "src" / "DemoProject.lean").read_text() == "import Topology.Main\nimport Topology.Helpers\n"
    assert "formal/src/Topology/Main.lean" in (project_root / ".archon" / "task_pending.md").read_text()

    manifest = json.loads((project_root / "manifests" / "phase3_archon_scaffolding.json").read_text())
    assert manifest["next_phase"] == "phase4_archon_proving"
    assert manifest["references_index_path"].endswith("phase3_reference_index.json")
    assert manifest["sorry_count"] == 2


def test_phase3_fallback_module_is_valid_lean_placeholder(tmp_path, monkeypatch):
    phase1, phase3 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(phase3, "_run_deerflow_agent", lambda *_args, **_kwargs: "not-json")

    state = _base_state("thread-phase3-fallback", "fallback-project", "Some statement.")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    (project_root / "informal" / "proofs" / "candidate_proof.md").write_text("Informal proof.")

    state = phase3.references_ingestion_node(state)
    state = phase3.project_init_node(state)
    state = phase3.autoformalize_node(state)

    fallback_content = (project_root / "formal" / "src" / "Main.lean").read_text()
    assert "import Mathlib" in fallback_content
    assert "def scaffoldPlaceholder : Prop := True" in fallback_content
    assert "theorem scaffold_placeholder" in fallback_content
    assert state["sorry_count"] == 1
