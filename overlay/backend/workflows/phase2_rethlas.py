"""
Phase 2 skeleton for the DeerFlow-native Rethlas reimplementation.

This phase establishes the paper-aligned Rethlas structure:
- problem-scoped memory initialization
- generation agent stage
- verification agent stage
- repair-loop-ready state model

It deliberately stops short of full theorem proving behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from .phase1_runtime import _memory_checkpointer, _runtime_root, bootstrap_layout


RETHLAS_SKILL_NAMES = [
    "obtain_immediate_conclusions",
    "search_mathematical_results",
    "query_memory",
    "construct_examples",
    "construct_counterexamples",
    "propose_decomposition",
    "direct_proving",
    "recursive_proving",
    "identify_key_failures",
    "verify_proof",
]

RETHLAS_MEMORY_CHANNELS = [
    "conclusions",
    "examples",
    "counterexamples",
    "decompositions",
    "proof_steps",
    "failed_paths",
    "verifications",
    "recursive_results",
    "search_results",
    "failures",
]


def _merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    merged: list[str] = []
    for item in (existing or []) + (new or []):
        if item not in merged:
            merged.append(item)
    return merged


class Phase2RethlasState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    project_name: str
    statement: str
    stage: Literal["BOOTSTRAP", "MEMORY_READY", "GENERATED", "VERIFIED", "FAILED"]
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
    problem_id: str
    rethlas_memory_root: str
    candidate_proof_path: str
    verification_report_path: str
    attempts: int
    verdict: Literal["pending", "correct", "wrong"]
    artifacts: Annotated[list[str], _merge_artifacts]


def _host_project_root(thread_id: str, project_name: str) -> Path:
    return _runtime_root() / "threads" / thread_id / "user-data" / "workspace" / project_name


def initialize_rethlas_memory(state: Phase2RethlasState) -> Phase2RethlasState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    problem_id = state.get("problem_id") or "default_problem"
    mem_root = project_root / "memory" / "rethlas" / problem_id
    mem_root.mkdir(parents=True, exist_ok=True)

    for channel in RETHLAS_MEMORY_CHANNELS:
        (mem_root / f"{channel}.jsonl").touch(exist_ok=True)

    manifest = {
        "phase": "phase2_rethlas",
        "problem_id": problem_id,
        "memory_channels": RETHLAS_MEMORY_CHANNELS,
        "skills": RETHLAS_SKILL_NAMES,
        "statement": state.get("statement", ""),
    }
    manifest_path = project_root / "manifests" / "phase2_rethlas.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    candidate_proof_path = project_root / "informal" / "proofs" / "candidate_proof.md"
    verification_report_path = project_root / "informal" / "verification" / "verification_report.json"

    return {
        **state,
        "stage": "MEMORY_READY",
        "problem_id": problem_id,
        "rethlas_memory_root": f"{state['memory_root']}/rethlas/{problem_id}",
        "candidate_proof_path": f"{state['informal_root']}/proofs/candidate_proof.md",
        "verification_report_path": f"{state['informal_root']}/verification/verification_report.json",
        "artifacts": [
            f"{project_name}/manifests/phase2_rethlas.json",
            f"{project_name}/memory/rethlas/{problem_id}/conclusions.jsonl",
        ],
    }


def generation_agent_node(state: Phase2RethlasState) -> Phase2RethlasState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    candidate_path = project_root / "informal" / "proofs" / "candidate_proof.md"
    content = [
        "# Candidate Informal Proof",
        "",
        f"## Statement",
        state.get("statement", "").strip() or "(missing statement)",
        "",
        "## Status",
        "Phase 2 skeleton only — generation agent runtime wiring starts here.",
        "",
        "## Planned Skills",
    ]
    content.extend(f"- {name}" for name in RETHLAS_SKILL_NAMES)
    candidate_path.write_text("\n".join(content))

    return {
        **state,
        "stage": "GENERATED",
        "attempts": state.get("attempts", 0) + 1,
        "artifacts": [f"{project_name}/informal/proofs/candidate_proof.md"],
    }


def verification_agent_node(state: Phase2RethlasState) -> Phase2RethlasState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    report_path = project_root / "informal" / "verification" / "verification_report.json"
    report = {
        "phase": "phase2_rethlas",
        "verdict": "pending",
        "reason": "Phase 2 skeleton only — verification agent runtime wiring starts here.",
        "candidate_proof_path": state.get("candidate_proof_path", ""),
        "attempts": state.get("attempts", 0),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    return {
        **state,
        "stage": "VERIFIED",
        "verdict": "pending",
        "artifacts": [f"{project_name}/informal/verification/verification_report.json"],
    }


def route_after_verification(state: Phase2RethlasState) -> str:
    return END


def build_phase2_rethlas_graph():
    graph = StateGraph(Phase2RethlasState)
    graph.add_node("bootstrap_layout", bootstrap_layout)
    graph.add_node("initialize_rethlas_memory", initialize_rethlas_memory)
    graph.add_node("generation_agent", generation_agent_node)
    graph.add_node("verification_agent", verification_agent_node)
    graph.set_entry_point("bootstrap_layout")
    graph.add_edge("bootstrap_layout", "initialize_rethlas_memory")
    graph.add_edge("initialize_rethlas_memory", "generation_agent")
    graph.add_edge("generation_agent", "verification_agent")
    graph.add_conditional_edges("verification_agent", route_after_verification, {END: END})
    return graph.compile(checkpointer=_memory_checkpointer())


def run_phase2_rethlas_workflow(
    thread_id: str,
    statement: str,
    project_name: str = "project",
    problem_id: str = "default_problem",
) -> dict:
    return build_phase2_rethlas_graph().invoke(
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
            "problem_id": problem_id,
            "rethlas_memory_root": "",
            "candidate_proof_path": "",
            "verification_report_path": "",
            "attempts": 0,
            "verdict": "pending",
            "artifacts": [],
        },
        {"configurable": {"thread_id": thread_id}},
    )
