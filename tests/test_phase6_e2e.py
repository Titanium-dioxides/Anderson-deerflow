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

    # Stub deerflow modules
    deerflow = types.ModuleType("deerflow")
    deerflow_models = types.ModuleType("deerflow.models")

    def fake_create_chat_model(*_args, **_kwargs):
        return None

    deerflow_models.create_chat_model = fake_create_chat_model
    deerflow.models = deerflow_models
    sys.modules["deerflow"] = deerflow
    sys.modules["deerflow.models"] = deerflow_models

    deerflow_agents = types.ModuleType("deerflow.agents")

    def fake_create_deerflow_agent(*_args, **_kwargs):
        class FakeAgent:
            def invoke(self, state, config=None):
                return {"messages": [HumanMessage(content=json.dumps({"result": "ok"}))]}
        return FakeAgent()

    deerflow_agents.create_deerflow_agent = fake_create_deerflow_agent
    deerflow.agents = deerflow_agents
    sys.modules["deerflow.agents"] = deerflow_agents

    deerflow_config = types.ModuleType("deerflow.config")
    deerflow_config.get_app_config = lambda: types.SimpleNamespace(models=[types.SimpleNamespace(name="deepseek-v4")])
    deerflow.config = deerflow_config
    sys.modules["deerflow.config"] = deerflow_config

    # Stub langchain.tools (needed by rethlas_skill_tools import chain)
    langchain_tools = types.ModuleType("langchain.tools")

    def fake_tool(*args, **kwargs):
        def decorator(func):
            func.name = kwargs.get("name", func.__name__) if kwargs else getattr(args[0], "__name__", "tool") if args else "tool"
            return func
        if args and callable(args[0]):
            return decorator(args[0])
        return decorator

    langchain_tools.tool = fake_tool
    sys.modules["langchain.tools"] = langchain_tools
    sys.modules["langchain"] = types.ModuleType("langchain")
    sys.modules["langchain"].tools = langchain_tools


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_phase_modules():
    _install_dependency_stubs()

    workflow_pkg = types.ModuleType("phase6_testpkg")
    workflow_pkg.__path__ = [str(WORKFLOWS_DIR)]
    sys.modules["phase6_testpkg"] = workflow_pkg

    phase1 = _load_module("phase6_testpkg.phase1_runtime", WORKFLOWS_DIR / "phase1_runtime.py")
    phase6 = _load_module("phase6_testpkg.phase6_e2e", WORKFLOWS_DIR / "phase6_e2e.py")
    return phase1, phase6


def _base_state(thread_id: str, project_name: str, statement: str, category: str = "SIMPLE") -> dict:
    return {
        "messages": [],
        "thread_id": thread_id,
        "project_name": project_name,
        "statement": statement,
        "problem_id": "test_problem",
        "category": category,
        "max_loops": 3,
        "parallelism": 2,
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
    }


def _fake_phase1_result(thread_id: str, project_name: str) -> dict:
    return {
        "messages": [],
        "thread_id": thread_id,
        "project_name": project_name,
        "stage": "READY",
        "workspace_root": "/mnt/user-data/workspace",
        "uploads_root": "/mnt/user-data/uploads",
        "outputs_root": "/mnt/user-data/outputs",
        "project_root": f"/mnt/user-data/workspace/{project_name}",
        "artifacts": [f"{project_name}/manifests/phase1_layout.json"],
    }


def _fake_phase2_result(thread_id: str, project_name: str) -> dict:
    return {
        "messages": [],
        "thread_id": thread_id,
        "project_name": project_name,
        "stage": "VERIFIED",
        "problem_id": "default_problem",
        "attempts": 1,
        "verdict": "pending",
        "rethlas_memory_root": f"/mnt/user-data/workspace/{project_name}/memory/rethlas/default_problem",
        "candidate_proof_path": f"/mnt/user-data/workspace/{project_name}/informal/proofs/candidate_proof.md",
        "verification_report_path": f"/mnt/user-data/workspace/{project_name}/informal/verification/verification_report.json",
        "artifacts": [
            f"{project_name}/manifests/phase2_rethlas.json",
            f"{project_name}/informal/proofs/candidate_proof.md",
            f"{project_name}/informal/verification/verification_report.json",
        ],
    }


def _fake_phase3_result(thread_id: str, project_name: str) -> dict:
    return {
        "messages": [],
        "thread_id": thread_id,
        "project_name": project_name,
        "stage": "MANIFEST_READY",
        "module_files": ["formal/src/Main.lean", "formal/src/Helpers.lean"],
        "sorry_count": 3,
        "references_index_path": f"/mnt/user-data/workspace/{project_name}/references/structured/phase3_reference_index.json",
        "lean_project_root": "formal",
        "archon_state_root": ".archon",
        "artifacts": [
            f"{project_name}/formal/src/Main.lean",
            f"{project_name}/formal/src/Helpers.lean",
            f"{project_name}/manifests/phase3_archon_scaffolding.json",
        ],
    }


def _fake_phase4_result(thread_id: str, project_name: str) -> dict:
    return {
        "messages": [],
        "thread_id": thread_id,
        "project_name": project_name,
        "stage": "COMPLETE",
        "pending": [],
        "completed": ["formal/src/Main.lean", "formal/src/Helpers.lean"],
        "blocked_files": [],
        "attempt_history": [
            {"loop_count": 0, "file": "formal/src/Main.lean", "status": "completed", "summary": "Done", "failure_mode": "", "execution_mode": "subagent_task", "tool_profile": "lean-lsp-reference-files"},
            {"loop_count": 0, "file": "formal/src/Helpers.lean", "status": "completed", "summary": "Done", "failure_mode": "", "execution_mode": "subagent_task", "tool_profile": "lean-lsp-reference-files"},
        ],
        "failure_modes": [],
        "review_history": [
            {"loop_count": 0, "global_strategy": "Default", "blockers": [], "continue_loop": False, "dead_end_files": []},
        ],
        "current_plan": {"loop_count": 0, "focus_files": ["formal/src/Main.lean"], "strategy": "Clear main theorem"},
        "review_summary": {"loop_count": 0, "pending": [], "completed": ["formal/src/Main.lean", "formal/src/Helpers.lean"], "stalled_files": [], "progress_made": True, "failure_counter": {}},
        "loop_count": 1,
        "max_loops": 3,
        "lean_subagent_type": "general-purpose",
        "lean_tool_profile": "lean-lsp-reference-files",
        "artifacts": [
            f"{project_name}/manifests/phase4_archon_proving.json",
            f"{project_name}/memory/archon/attempt_history.jsonl",
            f"{project_name}/memory/archon/review_history.jsonl",
        ],
    }


def _fake_phase5_result(thread_id: str, project_name: str, sorry_count: int = 0, compile_pass: bool = True) -> dict:
    return {
        "messages": [],
        "thread_id": thread_id,
        "project_name": project_name,
        "stage": "MANIFEST_READY",
        "sorry_axiom_report": {"pass": sorry_count == 0, "total_sorry_count": sorry_count, "total_axiom_count": 0},
        "total_sorry_count": sorry_count,
        "total_axiom_count": 0,
        "sorry_axiom_pass": sorry_count == 0,
        "compile_check_report": {"pass": compile_pass, "returncode": 0 if compile_pass else 1},
        "compile_pass": compile_pass,
        "compile_warnings": [],
        "polish_report": {"warning_review": "OK", "recommendations": ["Good"]},
        "warning_review": "OK",
        "redundancy_notes": "",
        "extractable_lemmas": [],
        "polish_recommendations": ["Good"],
        "polish_changes_applied": False,
        "artifact_archive_path": f"/mnt/user-data/workspace/{project_name}/scratch/{project_name}_formal_001.tar.gz",
        "export_report": {},
        "exported_paths": ["/mnt/user-data/outputs/summary.json", "/mnt/user-data/outputs/manifests/phase5_sync.json"],
        "proof_journal": {"phases": {"phase3": {}, "phase4": {}, "phase5": {}}, "final_verdict": "PASS" if sorry_count == 0 else "FAIL"},
        "deerflow_history_entries": [{"phase": "phase5"}],
        "artifacts": [f"{project_name}/manifests/phase5_polish.json", f"{project_name}/journal/proof_journal.json"],
    }


def _prepare_workspace(project_root: Path, statement: str = "Prove True.") -> None:
    """Create a minimal workspace structure that passes verification checks."""
    # Phase 1 directories
    for d in [
        "references/raw", "references/structured",
        "informal/proofs", "informal/verification",
        "formal/src",
        "memory/rethlas/default_problem", "memory/archon",
        "journal", "manifests", "scratch",
    ]:
        (project_root / d).mkdir(parents=True, exist_ok=True)

    # Phase 1 manifest
    (project_root / "manifests" / "phase1_layout.json").write_text(json.dumps({"phase": "phase1"}))

    # Phase 2 files
    (project_root / "informal" / "proofs" / "candidate_proof.md").write_text("# Candidate Proof\n\nTrivial proof.")
    (project_root / "informal" / "verification" / "verification_report.json").write_text(json.dumps({"verdict": "pending"}))
    (project_root / "manifests" / "phase2_rethlas.json").write_text(json.dumps({"phase": "phase2_rethlas"}))
    for ch in ["conclusions", "examples", "counterexamples", "decompositions", "proof_steps",
               "failed_paths", "verifications", "recursive_results", "search_results", "failures"]:
        (project_root / "memory" / "rethlas" / "default_problem" / f"{ch}.jsonl").write_text("")

    # Phase 3 files
    (project_root / "formal" / "lakefile.lean").write_text("import Lake\nopen Lake DSL\npackage test\n")
    (project_root / "formal" / "lean-toolchain").write_text("leanprover/lean4:v4.16.0\n")
    (project_root / ".archon").mkdir(parents=True, exist_ok=True)
    for fname in ["PROGRESS.md", "CLAUDE.md", "task_pending.md", "USER_HINTS.md"]:
        (project_root / ".archon" / fname).write_text(f"# {fname}\n")
    (project_root / "formal" / "src" / "Main.lean").write_text("import Mathlib\n\ntheorem t : True := by\n  trivial\n")
    (project_root / "formal" / "src" / "Helpers.lean").write_text("import Mathlib\nlemma h : True := trivial\n")
    (project_root / "manifests" / "phase3_archon_scaffolding.json").write_text(json.dumps({
        "phase": "phase3_archon_scaffolding",
        "module_files": ["formal/src/Main.lean", "formal/src/Helpers.lean"],
        "sorry_count": 3,
    }))

    # Phase 4 files
    (project_root / "memory" / "archon" / "attempt_history.jsonl").write_text(
        json.dumps({"loop_count": 0, "file": "formal/src/Main.lean", "status": "completed"}) + "\n"
    )
    (project_root / "memory" / "archon" / "review_history.jsonl").write_text(
        json.dumps({"loop_count": 0, "global_strategy": "default"}) + "\n"
    )
    (project_root / "manifests" / "phase4_archon_proving.json").write_text(json.dumps({
        "phase": "phase4_archon_proving",
        "stage": "COMPLETE",
        "completed": ["formal/src/Main.lean", "formal/src/Helpers.lean"],
    }))

    # Phase 5 files
    (project_root / "manifests" / "phase5_polish.json").write_text(json.dumps({"phase": "phase5_polish"}))
    (project_root / "journal" / "proof_journal.json").write_text(json.dumps({"phases": {}}))
    (project_root / "journal" / "deerflow_history_alignment.json").write_text(json.dumps([{"phase": "phase5"}]))

    # Tar archive for artifact check
    import tarfile
    (project_root / "scratch" / f"{project_root.name}_formal_001.tar.gz").write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 100)


# ---------------------------------------------------------------------------
# Test: E2E simple problem — all phases complete
# ---------------------------------------------------------------------------

def test_phase6_e2e_simple_true(tmp_path, monkeypatch):
    phase1, phase6 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-e2e-simple", "demo", "Prove that True is true.", "SIMPLE")
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_workspace(project_root, state["statement"])

    monkeypatch.setattr(phase6, "run_phase1_workflow", lambda tid, pn: _fake_phase1_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase2_rethlas_workflow", lambda tid, stmt, pn, pid: _fake_phase2_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase3_archon_scaffolding_workflow", lambda tid, stmt, pn, **kw: _fake_phase3_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase4_archon_proving_workflow", lambda tid, stmt, pn, ml, par: _fake_phase4_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase5_polish_workflow", lambda tid, pn: _fake_phase5_result(tid, pn))

    state = phase6.e2e_run_node(state)
    state = phase6.e2e_verify_node(state)

    assert state["stage"] == "VERIFIED"
    assert state["all_checks_pass"] is True

    report = state["structural_report"]
    assert report["overall_pass"] is True
    for phase_key in ["phase1", "phase2", "phase3", "phase4", "phase5"]:
        assert report["per_phase"][phase_key]["failed"] == 0, f"{phase_key} has failures"

    assert (project_root / "manifests" / "phase6_e2e_report.json").exists()


# ---------------------------------------------------------------------------
# Test: E2E simple problem — add zero
# ---------------------------------------------------------------------------

def test_phase6_e2e_simple_add_zero(tmp_path, monkeypatch):
    phase1, phase6 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-e2e-addzero", "demo", "Prove that n + 0 = n.", "SIMPLE")
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_workspace(project_root, state["statement"])

    monkeypatch.setattr(phase6, "run_phase1_workflow", lambda tid, pn: _fake_phase1_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase2_rethlas_workflow", lambda tid, stmt, pn, pid: _fake_phase2_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase3_archon_scaffolding_workflow", lambda tid, stmt, pn, **kw: _fake_phase3_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase4_archon_proving_workflow", lambda tid, stmt, pn, ml, par: _fake_phase4_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase5_polish_workflow", lambda tid, pn: _fake_phase5_result(tid, pn))

    state = phase6.e2e_run_node(state)
    state = phase6.e2e_verify_node(state)

    assert state["stage"] == "VERIFIED"
    assert state["all_checks_pass"] is True
    assert state["structural_report"]["per_phase"]["phase3"]["passed"] >= 8


# ---------------------------------------------------------------------------
# Test: E2E retrieval problem — even sum
# ---------------------------------------------------------------------------

def test_phase6_e2e_retrieval_even_sum(tmp_path, monkeypatch):
    phase1, phase6 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-e2e-even", "demo", "Prove sum of two evens is even.", "RETRIEVAL")
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_workspace(project_root, state["statement"])

    monkeypatch.setattr(phase6, "run_phase1_workflow", lambda tid, pn: _fake_phase1_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase2_rethlas_workflow", lambda tid, stmt, pn, pid: _fake_phase2_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase3_archon_scaffolding_workflow", lambda tid, stmt, pn, **kw: _fake_phase3_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase4_archon_proving_workflow", lambda tid, stmt, pn, ml, par: _fake_phase4_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase5_polish_workflow", lambda tid, pn: _fake_phase5_result(tid, pn))

    state = phase6.e2e_run_node(state)
    state = phase6.e2e_verify_node(state)

    assert state["stage"] == "VERIFIED"
    assert state["all_checks_pass"] is True
    assert state["structural_report"]["per_phase"]["phase2"]["failed"] == 0
    assert state["structural_report"]["per_phase"]["phase3"]["failed"] == 0


# ---------------------------------------------------------------------------
# Test: E2E complex problem — list append length
# ---------------------------------------------------------------------------

def test_phase6_e2e_complex_list_append(tmp_path, monkeypatch):
    phase1, phase6 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state(
        "thread-e2e-list", "demo",
        "Prove length (xs ++ ys) = length xs + length ys.",
        "COMPLEX",
    )
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_workspace(project_root, state["statement"])

    # For COMPLEX problems, use a Phase 4 result showing decomposition behavior
    def complex_phase4(tid, stmt, pn, ml, par):
        res = _fake_phase4_result(tid, pn)
        res["attempt_history"] = [
            {"loop_count": 0, "file": "formal/src/Main.lean", "status": "needs_retry", "summary": "Induction base case stuck.", "failure_mode": "missing_lemma_route", "execution_mode": "subagent_task"},
            {"loop_count": 0, "file": "formal/src/Helpers.lean", "status": "completed", "summary": "Helper lemma proved.", "failure_mode": "", "execution_mode": "subagent_task"},
            {"loop_count": 1, "file": "formal/src/Main.lean", "status": "completed", "summary": "Completed with helper lemma.", "failure_mode": "", "execution_mode": "subagent_task"},
        ]
        res["failure_modes"] = [{"loop_count": 0, "file": "formal/src/Main.lean", "failure_mode": "missing_lemma_route", "summary": "Base case needed separate lemma."}]
        res["review_history"] = [
            {"loop_count": 0, "global_strategy": "Reroute: prove helper lemma first.", "blockers": ["missing_lemma_route"], "continue_loop": True, "dead_end_files": []},
            {"loop_count": 1, "global_strategy": "Main theorem now uses helper.", "blockers": [], "continue_loop": False, "dead_end_files": []},
        ]
        return res

    monkeypatch.setattr(phase6, "run_phase1_workflow", lambda tid, pn: _fake_phase1_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase2_rethlas_workflow", lambda tid, stmt, pn, pid: _fake_phase2_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase3_archon_scaffolding_workflow", lambda tid, stmt, pn, **kw: _fake_phase3_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase4_archon_proving_workflow", complex_phase4)
    monkeypatch.setattr(phase6, "run_phase5_polish_workflow", lambda tid, pn: _fake_phase5_result(tid, pn))

    state = phase6.e2e_run_node(state)
    state = phase6.e2e_verify_node(state)

    assert state["stage"] == "VERIFIED"
    assert state["all_checks_pass"] is True

    # Verify decomposition structure: attempt history shows reroute
    attempt_count = len(state["phase4_result"]["attempt_history"])
    assert attempt_count == 3, f"Expected 3 attempts (1 retry + 2 completed), got {attempt_count}"
    assert len(state["phase4_result"]["review_history"]) == 2

    report = state["structural_report"]
    assert report["per_phase"]["phase4"]["failed"] == 0


# ---------------------------------------------------------------------------
# Test: structural invariants across all categories
# ---------------------------------------------------------------------------

def test_phase6_e2e_structural_invariants(tmp_path, monkeypatch):
    phase1, phase6 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    # Run all three categories through verification
    categories = ["SIMPLE", "RETRIEVAL", "COMPLEX"]
    results = {}

    for category in categories:
        tid = f"thread-e2e-struct-{category.lower()}"
        pn = f"demo-{category.lower()}"
        state = _base_state(tid, pn, f"Test statement for {category}.", category)
        project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / tid / "user-data" / "workspace" / pn
        _prepare_workspace(project_root, state["statement"])

        monkeypatch.setattr(phase6, "run_phase1_workflow", lambda tid, pn: _fake_phase1_result(tid, pn))
        monkeypatch.setattr(phase6, "run_phase2_rethlas_workflow", lambda tid, stmt, pn, pid: _fake_phase2_result(tid, pn))
        monkeypatch.setattr(phase6, "run_phase3_archon_scaffolding_workflow", lambda tid, stmt, pn, **kw: _fake_phase3_result(tid, pn))

        if category == "COMPLEX":
            monkeypatch.setattr(phase6, "run_phase4_archon_proving_workflow",
                lambda tid, stmt, pn, ml, par: {**_fake_phase4_result(tid, pn),
                    "attempt_history": _fake_phase4_result(tid, pn)["attempt_history"] * 2,
                    "review_history": _fake_phase4_result(tid, pn)["review_history"] * 2})
        else:
            monkeypatch.setattr(phase6, "run_phase4_archon_proving_workflow", lambda tid, stmt, pn, ml, par: _fake_phase4_result(tid, pn))

        monkeypatch.setattr(phase6, "run_phase5_polish_workflow", lambda tid, pn: _fake_phase5_result(tid, pn))

        state = phase6.e2e_run_node(state)
        state = phase6.e2e_verify_node(state)
        results[category] = state

    # Assert all categories pass
    for category in categories:
        assert results[category]["stage"] == "VERIFIED", f"{category} not VERIFIED"
        assert results[category]["all_checks_pass"] is True, f"{category} checks fail"

    # Assert structural invariants
    for category in categories:
        report = results[category]["structural_report"]
        # Phase 1: workspace directories exist
        assert report["per_phase"]["phase1"]["passed"] >= 10, f"{category} phase1 checks"
        # Phase 2: memory channels, candidate proof, verification report
        assert report["per_phase"]["phase2"]["passed"] >= 4, f"{category} phase2 checks"
        # Phase 3: Lean project, .archon/ state, module files
        assert report["per_phase"]["phase3"]["passed"] >= 8, f"{category} phase3 checks"
        # Phase 4: attempt history, review history, plan structure
        assert report["per_phase"]["phase4"]["passed"] >= 6, f"{category} phase4 checks"
        # Phase 5: sorry scan, compile, polish, export, history
        assert report["per_phase"]["phase5"]["passed"] >= 7, f"{category} phase5 checks"


# ---------------------------------------------------------------------------
# Test: E2E report generation and benchmark runner
# ---------------------------------------------------------------------------

def test_phase6_e2e_report_generation(tmp_path, monkeypatch):
    phase1, phase6 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-e2e-report", "demo", "Prove True.", "SIMPLE")
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_workspace(project_root, state["statement"])

    monkeypatch.setattr(phase6, "run_phase1_workflow", lambda tid, pn: _fake_phase1_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase2_rethlas_workflow", lambda tid, stmt, pn, pid: _fake_phase2_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase3_archon_scaffolding_workflow", lambda tid, stmt, pn, **kw: _fake_phase3_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase4_archon_proving_workflow", lambda tid, stmt, pn, ml, par: _fake_phase4_result(tid, pn))
    monkeypatch.setattr(phase6, "run_phase5_polish_workflow", lambda tid, pn: _fake_phase5_result(tid, pn))

    state = phase6.e2e_run_node(state)
    state = phase6.e2e_verify_node(state)

    # Verify E2E report structure
    report_path = project_root / "manifests" / "phase6_e2e_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())

    assert report["phase"] == "phase6_e2e_acceptance"
    assert report["category"] == "SIMPLE"
    assert report["thread_id"] == "thread-e2e-report"
    assert "structural_report" in report
    assert "per_phase" in report["structural_report"]

    sr = report["structural_report"]
    assert sr["overall_pass"] is True
    assert sr["total_passed"] == sr["total_checks"]
    assert sr["total_failed"] == 0

    # Verify per-phase summary
    for phase in ["phase1", "phase2", "phase3", "phase4", "phase5"]:
        assert sr["per_phase"][phase]["failed"] == 0
        assert sr["per_phase"][phase]["check_count"] > 0

    # Verify benchmark problem definitions
    assert "simple_true" in phase6.BENCHMARK_PROBLEMS
    assert "complex_list_append" in phase6.BENCHMARK_PROBLEMS
    assert phase6.BENCHMARK_PROBLEMS["simple_true"]["category"] == "SIMPLE"
    assert phase6.BENCHMARK_PROBLEMS["retrieval_even_sum"]["category"] == "RETRIEVAL"
    assert phase6.BENCHMARK_PROBLEMS["complex_comp_antisym"]["category"] == "COMPLEX"

    # Verify benchmark runner handles unknown problem
    result = phase6.run_benchmark("nonexistent")
    assert "error" in result
