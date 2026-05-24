from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / "overlay" / "backend" / "workflows"


def _install_dependency_stubs(with_sqlite: bool = False) -> None:
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

        def compile(self, **_kwargs):
            return self

    langgraph_graph.StateGraph = StateGraph
    langgraph_graph_message.add_messages = lambda _existing, new: new
    langgraph.graph = langgraph_graph
    sys.modules["langgraph"] = langgraph
    sys.modules["langgraph.graph"] = langgraph_graph
    sys.modules["langgraph.graph.message"] = langgraph_graph_message

    if with_sqlite:
        sqlite_mod = types.ModuleType("langgraph.checkpoint.sqlite")

        class FakeSqliteSaver:
            @classmethod
            def from_conn_string(cls, conn_string: str):
                return {"kind": "sqlite", "conn_string": conn_string}

        sqlite_mod.SqliteSaver = FakeSqliteSaver
        sys.modules["langgraph.checkpoint.sqlite"] = sqlite_mod
    else:
        memory_mod = types.ModuleType("langgraph.checkpoint.memory")

        class FakeMemorySaver:
            pass

        memory_mod.MemorySaver = FakeMemorySaver
        sys.modules["langgraph.checkpoint.memory"] = memory_mod


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_phase1_prefers_sqlite_checkpointer_and_logs_runtime_event(tmp_path, monkeypatch):
    _install_dependency_stubs(with_sqlite=True)
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    phase1 = _load_module("phase1_runtime_testpkg", WORKFLOWS_DIR / "phase1_runtime.py")

    checkpointer = phase1._memory_checkpointer()
    assert checkpointer["kind"] == "sqlite"
    assert checkpointer["conn_string"].endswith("langgraph.sqlite")

    state = {
        "messages": [],
        "thread_id": "thread-phase1",
        "project_name": "demo",
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
        "artifacts": [],
    }
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": "thread-phase1"}})

    history_path = tmp_path / "runtime" / "threads" / "thread-phase1" / "runtime" / "run_history.jsonl"
    assert history_path.exists()
    entries = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
    assert entries[-1]["phase"] == "phase1_runtime"
    assert entries[-1]["node"] == "bootstrap_layout"
    assert state["stage"] == "READY"
