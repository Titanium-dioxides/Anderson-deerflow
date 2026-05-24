"""
Phase 1 runtime skeleton for the Archon + Rethlas DeerFlow-native rewrite.

This module intentionally focuses on runtime concerns only:
- thread-scoped workspace layout
- DeerFlow-compatible path semantics
- checkpoint-ready LangGraph skeleton
- artifact/manifest bootstrap

It does not yet implement paper-level proving logic.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Shared artifacts reducer — must be the *same object* across all phases."""
    merged: list[str] = []
    for item in (existing or []) + (new or []):
        if item not in merged:
            merged.append(item)
    return merged

# Backward-compatible alias
_merge_artifacts = merge_artifacts


class Phase1State(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    project_name: str
    stage: Literal["BOOTSTRAP", "READY"]
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
    artifacts: Annotated[list[str], merge_artifacts]


def _thread_id_from_config(config) -> str:
    if config and isinstance(config, dict):
        configurable = config.get("configurable", {})
        if isinstance(configurable, dict) and configurable.get("thread_id"):
            return str(configurable["thread_id"])
    return "archon-deerflow-phase1"


def _runtime_root() -> Path:
    env_root = os.environ.get("ARCHON_DEERFLOW_RUNTIME_ROOT")
    if env_root:
        return Path(env_root)
    return Path(".deerflow_runtime")


def _host_user_data_root(thread_id: str) -> Path:
    return _runtime_root() / "threads" / thread_id / "user-data"


def _host_thread_root(thread_id: str) -> Path:
    return _runtime_root() / "threads" / thread_id


def _virtual_user_data_root() -> Path:
    return Path("/mnt/user-data")


def _host_runtime_root(thread_id: str) -> Path:
    return _host_thread_root(thread_id) / "runtime"


def _host_runtime_history_path(thread_id: str) -> Path:
    return _host_runtime_root(thread_id) / "run_history.jsonl"


def _host_runtime_checkpoints_dir() -> Path:
    return _runtime_root() / "checkpoints"


def _host_runtime_checkpoint_path() -> Path:
    return _host_runtime_checkpoints_dir() / "langgraph.sqlite"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_runtime_event(thread_id: str, phase: str, node: str, payload: dict | None = None) -> None:
    path = _host_runtime_history_path(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": _utc_now_iso(),
        "thread_id": thread_id,
        "phase": phase,
        "node": node,
        "payload": payload or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_runtime_history(thread_id: str) -> list[dict]:
    path = _host_runtime_history_path(thread_id)
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _build_layout(thread_id: str, project_name: str) -> dict[str, str]:
    host_root = _host_user_data_root(thread_id)
    virtual_root = _virtual_user_data_root()
    return {
        "workspace_root": str(virtual_root / "workspace"),
        "uploads_root": str(virtual_root / "uploads"),
        "outputs_root": str(virtual_root / "outputs"),
        "project_root": str(virtual_root / "workspace" / project_name),
        "references_root": str(virtual_root / "workspace" / project_name / "references"),
        "informal_root": str(virtual_root / "workspace" / project_name / "informal"),
        "formal_root": str(virtual_root / "workspace" / project_name / "formal"),
        "memory_root": str(virtual_root / "workspace" / project_name / "memory"),
        "journal_root": str(virtual_root / "workspace" / project_name / "journal"),
        "manifests_root": str(virtual_root / "workspace" / project_name / "manifests"),
        "scratch_root": str(virtual_root / "workspace" / project_name / "scratch"),
        "_host_workspace_root": str(host_root / "workspace"),
        "_host_uploads_root": str(host_root / "uploads"),
        "_host_outputs_root": str(host_root / "outputs"),
        "_host_project_root": str(host_root / "workspace" / project_name),
    }


def bootstrap_layout(state: Phase1State, config=None) -> Phase1State:
    thread_id = state.get("thread_id") or _thread_id_from_config(config)
    project_name = state.get("project_name") or "project"
    layout = _build_layout(thread_id, project_name)

    host_dirs = [
        Path(layout["_host_workspace_root"]),
        Path(layout["_host_uploads_root"]),
        Path(layout["_host_outputs_root"]),
        Path(layout["_host_project_root"]) / "references" / "raw",
        Path(layout["_host_project_root"]) / "references" / "ocr",
        Path(layout["_host_project_root"]) / "references" / "structured",
        Path(layout["_host_project_root"]) / "informal" / "proofs",
        Path(layout["_host_project_root"]) / "informal" / "verification",
        Path(layout["_host_project_root"]) / "informal" / "plans",
        Path(layout["_host_project_root"]) / "informal" / "failures",
        Path(layout["_host_project_root"]) / "formal",
        Path(layout["_host_project_root"]) / "memory" / "rethlas",
        Path(layout["_host_project_root"]) / "memory" / "archon",
        Path(layout["_host_project_root"]) / "journal",
        Path(layout["_host_project_root"]) / "manifests",
        Path(layout["_host_project_root"]) / "scratch",
    ]
    for directory in host_dirs:
        directory.mkdir(parents=True, exist_ok=True)
    _host_runtime_root(thread_id).mkdir(parents=True, exist_ok=True)

    manifest_path = Path(layout["_host_project_root"]) / "manifests" / "phase1_layout.json"
    manifest = {
        "thread_id": thread_id,
        "project_name": project_name,
        "virtual_paths": {
            key: value
            for key, value in layout.items()
            if not key.startswith("_host_")
        },
        "host_paths": {
            key.removeprefix("_host_"): value
            for key, value in layout.items()
            if key.startswith("_host_")
        },
        "phase": "phase1",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase1_runtime",
        "bootstrap_layout",
        {
            "project_name": project_name,
            "project_root": layout["project_root"],
        },
    )

    artifact_rel = f"{project_name}/manifests/phase1_layout.json"
    return {
        **state,
        "thread_id": thread_id,
        "project_name": project_name,
        "stage": "READY",
        "workspace_root": layout["workspace_root"],
        "uploads_root": layout["uploads_root"],
        "outputs_root": layout["outputs_root"],
        "project_root": layout["project_root"],
        "references_root": layout["references_root"],
        "informal_root": layout["informal_root"],
        "formal_root": layout["formal_root"],
        "memory_root": layout["memory_root"],
        "journal_root": layout["journal_root"],
        "manifests_root": layout["manifests_root"],
        "scratch_root": layout["scratch_root"],
        "artifacts": [artifact_rel],
    }


def _memory_checkpointer():
    checkpoint_dir = _host_runtime_checkpoints_dir()
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        checkpoint_path = _host_runtime_checkpoint_path()
        if hasattr(SqliteSaver, "from_conn_string"):
            return SqliteSaver.from_conn_string(str(checkpoint_path))
        return SqliteSaver(str(checkpoint_path))
    except Exception:
        try:
            from langgraph.checkpoint.memory import MemorySaver
            return MemorySaver()
        except Exception:
            return None


def build_phase1_graph():
    graph = StateGraph(Phase1State)
    graph.add_node("bootstrap_layout", bootstrap_layout)
    graph.set_entry_point("bootstrap_layout")
    graph.set_finish_point("bootstrap_layout")
    return graph.compile(checkpointer=_memory_checkpointer())


def run_phase1_workflow(
    thread_id: str,
    project_name: str = "project",
) -> dict:
    return build_phase1_graph().invoke(
        {
            "messages": [],
            "thread_id": thread_id,
            "project_name": project_name,
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
        },
        {"configurable": {"thread_id": thread_id}},
    )
