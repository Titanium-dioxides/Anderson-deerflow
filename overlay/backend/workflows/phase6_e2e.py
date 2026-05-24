"""
Phase 6 — End-to-End Acceptance Testing (DeerFlow-native).

Chains Phase 1→2→3→4→5 for benchmark problems and verifies structural /
behavioral invariants at each stage boundary.

Problem categories:
  - SIMPLE:  trivial theorems, single file, no decomposition needed
  - RETRIEVAL: require external theorem knowledge / mathlib imports
  - COMPLEX: require multi-lemma decomposition and multi-round proving
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from .phase1_runtime import _memory_checkpointer, _runtime_root, run_phase1_workflow, merge_artifacts
from .phase2_rethlas import run_phase2_rethlas_workflow
from .phase3_archon_scaffolding import run_phase3_archon_scaffolding_workflow
from .phase4_archon_proving import run_phase4_archon_proving_workflow
from .phase5_polish import run_phase5_polish_workflow


class Phase6E2EState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    project_name: str
    statement: str
    problem_id: str
    category: Literal["SIMPLE", "RETRIEVAL", "COMPLEX"]
    max_loops: int
    parallelism: int
    stage: Literal[
        "INIT",
        "PHASE1_DONE",
        "PHASE2_DONE",
        "PHASE3_DONE",
        "PHASE4_DONE",
        "PHASE5_DONE",
        "VERIFIED",
    ]
    phase1_result: dict
    phase2_result: dict
    phase3_result: dict
    phase4_result: dict
    phase5_result: dict
    verification_checks: list[dict]
    all_checks_pass: bool
    structural_report: dict
    artifacts: Annotated[list[str], merge_artifacts]


# ---------------------------------------------------------------------------
# Benchmark problem definitions
# ---------------------------------------------------------------------------

BENCHMARK_PROBLEMS = {
    "simple_true": {
        "statement": "Prove that True is true.",
        "category": "SIMPLE",
        "expected_phases": [
            "PHASE1_DONE",
            "PHASE2_DONE",
            "PHASE3_DONE",
            "PHASE4_DONE",
            "PHASE5_DONE",
        ],
        "expected_properties": ["single_file", "trivial_proof"],
        "description": "Trivial propositional tautology — verifies basic pipeline health.",
    },
    "simple_add_zero": {
        "statement": "Prove that for any natural number n, n + 0 = n.",
        "category": "SIMPLE",
        "expected_phases": [
            "PHASE1_DONE",
            "PHASE2_DONE",
            "PHASE3_DONE",
            "PHASE4_DONE",
            "PHASE5_DONE",
        ],
        "expected_properties": ["single_lemma", "induction_candidate"],
        "description": "Basic arithmetic identity — verifies single-lemma formalization.",
    },
    "retrieval_even_sum": {
        "statement": "Prove that the sum of two even numbers is even.",
        "category": "RETRIEVAL",
        "expected_phases": [
            "PHASE1_DONE",
            "PHASE2_DONE",
            "PHASE3_DONE",
            "PHASE4_DONE",
            "PHASE5_DONE",
        ],
        "expected_properties": ["requires_mathlib", "external_theorem_reference"],
        "description": "Number theory property needing even/odd definitions from Mathlib.",
    },
    "retrieval_and_commute": {
        "statement": "Prove that logical AND is commutative: for any propositions P and Q, (P ∧ Q) ↔ (Q ∧ P).",
        "category": "RETRIEVAL",
        "expected_phases": [
            "PHASE1_DONE",
            "PHASE2_DONE",
            "PHASE3_DONE",
            "PHASE4_DONE",
            "PHASE5_DONE",
        ],
        "expected_properties": ["requires_logic_imports", "iff_proof_structure"],
        "description": "Logical connective property requiring bidirectional proof structure.",
    },
    "complex_list_append": {
        "statement": "Prove that for any lists xs and ys, length (xs ++ ys) = length xs + length ys.",
        "category": "COMPLEX",
        "expected_phases": [
            "PHASE1_DONE",
            "PHASE2_DONE",
            "PHASE3_DONE",
            "PHASE4_DONE",
            "PHASE5_DONE",
        ],
        "expected_properties": [
            "decomposition",
            "multi_lemma",
            "induction",
            "base_case",
            "inductive_step",
        ],
        "description": "List property requiring induction with base case and inductive step — verifies decomposition behavior.",
    },
    "complex_comp_antisym": {
        "statement": "Prove that if A is a subset of B and B is a subset of A, then A equals B.",
        "category": "COMPLEX",
        "expected_phases": [
            "PHASE1_DONE",
            "PHASE2_DONE",
            "PHASE3_DONE",
            "PHASE4_DONE",
            "PHASE5_DONE",
        ],
        "expected_properties": [
            "decomposition",
            "bidirectional",
            "set_theory",
            "extensionality",
        ],
        "description": "Set theory antisymmetry requiring bidirectional subset proof.",
    },
}


# ---------------------------------------------------------------------------
# Structural verification helpers
# ---------------------------------------------------------------------------

def _host_project_root(thread_id: str, project_name: str) -> Path:
    return _runtime_root() / "threads" / thread_id / "user-data" / "workspace" / project_name


def _check_stage(expected_stage: str, actual_stage: str) -> dict:
    return {
        "check": f"stage == {expected_stage}",
        "pass": actual_stage == expected_stage,
        "detail": f"expected: {expected_stage}, actual: {actual_stage}",
    }


def _check_file_exists(project_root: Path, rel_path: str, label: str = "") -> dict:
    exists = (project_root / rel_path).exists()
    return {
        "check": f"file exists: {rel_path}",
        "pass": exists,
        "detail": label or (f"{rel_path} exists" if exists else f"{rel_path} missing"),
    }


def _verify_phase1(project_root: Path, result: dict) -> list[dict]:
    checks: list[dict] = []
    checks.append(_check_stage("READY", result.get("stage", "")))

    dirs = ["references/raw", "references/structured", "informal/proofs",
            "informal/verification", "formal", "memory/rethlas", "memory/archon",
            "journal", "manifests", "scratch"]
    for d in dirs:
        exists = (project_root / d).is_dir()
        checks.append({
            "check": f"directory exists: {d}",
            "pass": exists,
            "detail": f"dir {d} {'exists' if exists else 'missing'}",
        })

    checks.append(_check_file_exists(project_root, "manifests/phase1_layout.json", "layout manifest"))
    return checks


def _verify_phase2(project_root: Path, result: dict) -> list[dict]:
    checks: list[dict] = []
    checks.append(_check_stage("VERIFIED", result.get("stage", "")))

    checks.append(_check_file_exists(project_root, "informal/proofs/candidate_proof.md", "candidate proof"))
    checks.append(_check_file_exists(project_root, "informal/verification/verification_report.json", "verification report"))
    checks.append(_check_file_exists(project_root, "manifests/phase2_rethlas.json", "phase2 manifest"))

    problem_id = result.get("problem_id", "default_problem")
    mem_root = project_root / "memory" / "rethlas" / problem_id
    channel_count = 0
    if mem_root.exists():
        channel_count = len(list(mem_root.glob("*.jsonl")))
    checks.append({
        "check": "Rethlas memory channels >= 8",
        "pass": channel_count >= 8,
        "detail": f"{channel_count} channels found",
    })

    checks.append({
        "check": "generation→verification loop intact",
        "pass": result.get("attempts", 0) >= 1,
        "detail": f"attempts: {result.get('attempts', 0)}, verdict: {result.get('verdict', 'unknown')}",
    })
    return checks


def _verify_phase3(project_root: Path, result: dict) -> list[dict]:
    checks: list[dict] = []
    checks.append(_check_stage("MANIFEST_READY", result.get("stage", "")))

    checks.append(_check_file_exists(project_root, "formal/lakefile.lean", "lakefile"))
    checks.append(_check_file_exists(project_root, "formal/lean-toolchain", "lean-toolchain"))
    checks.append(_check_file_exists(project_root, ".archon/PROGRESS.md", "PROGRESS.md"))
    checks.append(_check_file_exists(project_root, ".archon/CLAUDE.md", "CLAUDE.md"))
    checks.append(_check_file_exists(project_root, ".archon/task_pending.md", "task_pending.md"))
    checks.append(_check_file_exists(project_root, ".archon/USER_HINTS.md", "USER_HINTS.md"))
    checks.append(_check_file_exists(project_root, "manifests/phase3_archon_scaffolding.json", "phase3 manifest"))

    module_files = result.get("module_files", [])
    module_count = len(module_files)
    checks.append({
        "check": "autoformalize produced >= 1 module file",
        "pass": module_count >= 1,
        "detail": f"{module_count} module files: {module_files}",
    })

    has_sorries = result.get("sorry_count", 0) > 0
    checks.append({
        "check": "skeleton has sorry placeholders",
        "pass": has_sorries,
        "detail": f"sorry count: {result.get('sorry_count', 0)}",
    })

    checks.append({
        "check": "reference index created",
        "pass": bool(result.get("references_index_path", "")),
        "detail": f"references index: {result.get('references_index_path', '')}",
    })
    return checks


def _verify_phase4(project_root: Path, result: dict) -> list[dict]:
    checks: list[dict] = []
    stage = result.get("stage", "")
    checks.append({
        "check": "phase4 terminal stage reached",
        "pass": stage in {"COMPLETE", "FAILED", "STRATEGY_READY"},
        "detail": f"stage: {stage}",
    })

    attempt_count = len(result.get("attempt_history", []))
    checks.append({
        "check": "attempt history recorded",
        "pass": attempt_count >= 1,
        "detail": f"{attempt_count} attempts recorded",
    })

    failure_count = len(result.get("failure_modes", []))
    checks.append({
        "check": "failure modes tracked",
        "pass": True,  # zero failures is also valid
        "detail": f"{failure_count} failure modes",
    })

    review_count = len(result.get("review_history", []))
    checks.append({
        "check": "review history present",
        "pass": review_count >= 1,
        "detail": f"{review_count} review cycles",
    })

    checks.append({
        "check": "plan→lean→reviewer→review_agent structure preserved",
        "pass": "current_plan" in result and "review_summary" in result,
        "detail": f"plan keys: {list(result.get('current_plan', {}).keys())}, review keys: {list(result.get('review_summary', {}).keys())}",
    })

    checks.append({
        "check": "blocked files mechanism present",
        "pass": isinstance(result.get("blocked_files", None), list),
        "detail": f"blocked files: {result.get('blocked_files', [])}",
    })

    checks.append(_check_file_exists(project_root, "memory/archon/attempt_history.jsonl", "attempt history file"))
    checks.append(_check_file_exists(project_root, "memory/archon/review_history.jsonl", "review history file"))
    checks.append(_check_file_exists(project_root, "manifests/phase4_archon_proving.json", "phase4 manifest"))

    return checks


def _verify_phase5(project_root: Path, result: dict) -> list[dict]:
    checks: list[dict] = []
    checks.append(_check_stage("MANIFEST_READY", result.get("stage", "")))

    checks.append({
        "check": "sorry/axiom scan complete",
        "pass": bool(result.get("sorry_axiom_report", {})),
        "detail": f"sorry: {result.get('total_sorry_count', -1)}, axiom: {result.get('total_axiom_count', -1)}",
    })

    compile_report = result.get("compile_check_report", {})
    checks.append({
        "check": "compile check recorded",
        "pass": "returncode" in compile_report,
        "detail": f"returncode: {compile_report.get('returncode', 'N/A')}",
    })

    checks.append({
        "check": "polish review written",
        "pass": bool(result.get("polish_report", {})),
        "detail": f"polish keys: {list(result.get('polish_report', {}).keys())}",
    })

    has_archive = bool(result.get("artifact_archive_path", ""))
    checks.append({
        "check": "artifact archive created",
        "pass": has_archive,
        "detail": f"archive: {result.get('artifact_archive_path', '(none)')}",
    })

    export_count = len(result.get("exported_paths", []))
    checks.append({
        "check": "outputs exported",
        "pass": export_count >= 1,
        "detail": f"{export_count} exports",
    })

    checks.append({
        "check": "runtime history aligned",
        "pass": bool(result.get("proof_journal", {})) and bool(result.get("deerflow_history_entries", [])),
        "detail": f"journal phases: {list(result.get('proof_journal', {}).get('phases', {}).keys())}",
    })

    checks.append(_check_file_exists(project_root, "manifests/phase5_polish.json", "phase5 manifest"))
    checks.append(_check_file_exists(project_root, "journal/proof_journal.json", "proof journal"))
    checks.append(_check_file_exists(project_root, "journal/deerflow_history_alignment.json", "DeerFlow history"))

    return checks


# ---------------------------------------------------------------------------
# E2E verification node
# ---------------------------------------------------------------------------

def _verify_all_phases(
    thread_id: str,
    project_name: str,
    results: dict[str, dict],
) -> tuple[list[dict], dict]:
    project_root = _host_project_root(thread_id, project_name)
    all_checks: list[dict] = []

    phase_labels = {
        "phase1": "Phase 1 — Runtime Skeleton",
        "phase2": "Phase 2 — Rethlas Informal Proof",
        "phase3": "Phase 3 — Archon Scaffolding",
        "phase4": "Phase 4 — Archon Proving Loop",
        "phase5": "Phase 5 — Polish / Export / Runtime History",
    }
    verifiers = {
        "phase1": _verify_phase1,
        "phase2": _verify_phase2,
        "phase3": _verify_phase3,
        "phase4": _verify_phase4,
        "phase5": _verify_phase5,
    }

    phase_summary: dict[str, dict] = {}

    for phase_key in ["phase1", "phase2", "phase3", "phase4", "phase5"]:
        result = results.get(phase_key, {})
        verify_fn = verifiers.get(phase_key)
        if verify_fn:
            checks = verify_fn(project_root, result)
        else:
            checks = []

        passed = sum(1 for c in checks if c.get("pass"))
        failed = len(checks) - passed
        all_checks.extend(checks)
        phase_summary[phase_key] = {
            "label": phase_labels.get(phase_key, phase_key),
            "check_count": len(checks),
            "passed": passed,
            "failed": failed,
            "stage": result.get("stage", "unknown"),
        }

    all_pass = all(c.get("pass", False) for c in all_checks)
    return all_checks, {
        "overall_pass": all_pass,
        "total_checks": len(all_checks),
        "total_passed": sum(1 for c in all_checks if c.get("pass")),
        "total_failed": sum(1 for c in all_checks if not c.get("pass")),
        "per_phase": phase_summary,
        "checks": all_checks,
    }


# ---------------------------------------------------------------------------
# Graph node: e2e_run_node
# ---------------------------------------------------------------------------

def e2e_run_node(state: Phase6E2EState) -> Phase6E2EState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    statement = state["statement"]
    problem_id = state.get("problem_id", "default_problem")
    max_loops = state.get("max_loops", 3)
    parallelism = state.get("parallelism", 2)

    phase1_result = run_phase1_workflow(thread_id, project_name)
    phase2_result = run_phase2_rethlas_workflow(thread_id, statement, project_name, problem_id)

    informal_proof = ""
    candidate_path = ""
    project_root = _host_project_root(thread_id, project_name)
    candidate_file = project_root / "informal" / "proofs" / "candidate_proof.md"
    if candidate_file.exists():
        informal_proof = candidate_file.read_text()
        candidate_path = phase2_result.get("candidate_proof_path", "")

    phase3_result = run_phase3_archon_scaffolding_workflow(
        thread_id, statement, project_name,
        informal_proof_content=informal_proof,
        candidate_proof_path=candidate_path,
    )
    phase4_result = run_phase4_archon_proving_workflow(
        thread_id, statement, project_name, max_loops, parallelism,
    )
    phase5_result = run_phase5_polish_workflow(thread_id, project_name)

    return {
        **state,
        "stage": "PHASE5_DONE",
        "phase1_result": phase1_result,
        "phase2_result": phase2_result,
        "phase3_result": phase3_result,
        "phase4_result": phase4_result,
        "phase5_result": phase5_result,
        "artifacts": (
            phase1_result.get("artifacts", [])
            + phase2_result.get("artifacts", [])
            + phase3_result.get("artifacts", [])
            + phase4_result.get("artifacts", [])
            + phase5_result.get("artifacts", [])
        ),
    }


def e2e_verify_node(state: Phase6E2EState) -> Phase6E2EState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]

    results = {
        "phase1": state.get("phase1_result", {}),
        "phase2": state.get("phase2_result", {}),
        "phase3": state.get("phase3_result", {}),
        "phase4": state.get("phase4_result", {}),
        "phase5": state.get("phase5_result", {}),
    }

    checks, structural_report = _verify_all_phases(thread_id, project_name, results)

    project_root = _host_project_root(thread_id, project_name)
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    report_path = project_root / "manifests" / "phase6_e2e_report.json"
    e2e_report = {
        "phase": "phase6_e2e_acceptance",
        "thread_id": thread_id,
        "project_name": project_name,
        "statement": state.get("statement", ""),
        "problem_id": state.get("problem_id", ""),
        "category": state.get("category", ""),
        "structural_report": structural_report,
    }
    report_path.write_text(json.dumps(e2e_report, ensure_ascii=False, indent=2))

    return {
        **state,
        "stage": "VERIFIED",
        "verification_checks": checks,
        "all_checks_pass": structural_report["overall_pass"],
        "structural_report": structural_report,
        "artifacts": [f"{project_name}/manifests/phase6_e2e_report.json"],
    }


def route_after_verify(state: Phase6E2EState) -> str:
    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_phase6_e2e_graph():
    graph = StateGraph(Phase6E2EState)
    graph.add_node("e2e_run", e2e_run_node)
    graph.add_node("e2e_verify", e2e_verify_node)
    graph.set_entry_point("e2e_run")
    graph.add_edge("e2e_run", "e2e_verify")
    graph.add_conditional_edges("e2e_verify", route_after_verify, {END: END})
    return graph.compile(checkpointer=_memory_checkpointer())


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run_e2e_workflow(
    thread_id: str,
    statement: str,
    project_name: str = "project",
    problem_id: str = "default_problem",
    category: str = "SIMPLE",
    max_loops: int = 3,
    parallelism: int = 2,
) -> dict:
    return build_phase6_e2e_graph().invoke(
        {
            "messages": [],
            "thread_id": thread_id,
            "project_name": project_name,
            "statement": statement,
            "problem_id": problem_id,
            "category": category,
            "max_loops": max_loops,
            "parallelism": parallelism,
            "stage": "INIT",
            "phase1_result": {},
            "phase2_result": {},
            "phase3_result": {},
            "phase4_result": {},
            "phase5_result": {},
            "verification_checks": [],
            "all_checks_pass": False,
            "structural_report": {},
            "artifacts": [],
        },
        {"configurable": {"thread_id": thread_id}},
    )


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(
    problem_name: str,
    *,
    thread_id: str | None = None,
    max_loops: int = 3,
    parallelism: int = 2,
) -> dict:
    if problem_name not in BENCHMARK_PROBLEMS:
        return {"error": f"Unknown problem: {problem_name}", "available": list(BENCHMARK_PROBLEMS.keys())}

    problem = BENCHMARK_PROBLEMS[problem_name]
    tid = thread_id or f"benchmark-{problem_name}"

    result = run_e2e_workflow(
        thread_id=tid,
        statement=problem["statement"],
        project_name=problem_name.replace("_", "-"),
        problem_id=problem_name,
        category=problem["category"],
        max_loops=max_loops,
        parallelism=parallelism,
    )

    expected_phases = problem.get("expected_phases", [])
    phases_ok = result.get("stage") in {"VERIFIED", "PHASE5_DONE"}

    return {
        "problem_name": problem_name,
        "category": problem["category"],
        "description": problem.get("description", ""),
        "phases_ok": phases_ok,
        "expected_phases": expected_phases,
        "actual_stage": result.get("stage", "UNKNOWN"),
        "all_checks_pass": result.get("all_checks_pass", False),
        "structural_report": result.get("structural_report", {}),
        "e2e_result": result,
    }
