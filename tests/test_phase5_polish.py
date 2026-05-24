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

    workflow_pkg = types.ModuleType("phase5_testpkg")
    workflow_pkg.__path__ = [str(WORKFLOWS_DIR)]
    sys.modules["phase5_testpkg"] = workflow_pkg

    phase1 = _load_module("phase5_testpkg.phase1_runtime", WORKFLOWS_DIR / "phase1_runtime.py")
    phase5 = _load_module("phase5_testpkg.phase5_polish", WORKFLOWS_DIR / "phase5_polish.py")
    return phase1, phase5


def _base_state(thread_id: str, project_name: str) -> dict:
    return {
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
        "phase4_manifest": {},
        "phase4_stage": "",
        "phase4_loop_count": 0,
        "phase4_pending": [],
        "phase4_completed": [],
        "phase4_failure_modes": [],
        "module_files": [],
        "sorry_axiom_report": {},
        "total_sorry_count": 0,
        "total_axiom_count": 0,
        "sorry_axiom_pass": False,
        "compile_check_report": {},
        "compile_pass": False,
        "compile_warnings": [],
        "polish_report": {},
        "warning_review": "",
        "redundancy_notes": "",
        "extractable_lemmas": [],
        "polish_recommendations": [],
        "polish_changes_applied": False,
        "artifact_archive_path": "",
        "artifact_manifest": {},
        "export_report": {},
        "exported_paths": [],
        "proof_journal": {},
        "deerflow_history_entries": [],
        "artifacts": [],
    }


def _prepare_phase4_workspace(project_root: Path, stage: str, pending: list[str], completed: list[str]) -> None:
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    (project_root / "formal" / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "scratch").mkdir(parents=True, exist_ok=True)
    (project_root / "journal").mkdir(parents=True, exist_ok=True)
    (project_root / "manifests" / "phase4_archon_proving.json").write_text(
        json.dumps(
            {
                "phase": "phase4_archon_proving",
                "stage": stage,
                "loop_count": 2,
                "max_loops": 3,
                "pending": pending,
                "completed": completed,
                "failure_modes": (
                    [{"loop_count": 1, "file": pending[0], "failure_mode": "blocked", "summary": "Dead end."}]
                    if pending
                    else []
                ),
                "blocked_files": pending,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    # Write completed files without sorries
    for cf in completed:
        fpath = project_root / cf
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text("import Mathlib\n\ntheorem done : True := by\n  trivial\n")
    # Write pending files with sorries
    for pf in pending:
        fpath = project_root / pf
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text("import Mathlib\n\ntheorem stuck : True := by\n  sorry\n")

    (project_root / "manifests" / "phase3_archon_scaffolding.json").write_text(
        json.dumps(
            {
                "phase": "phase3_archon_scaffolding",
                "module_files": pending + completed,
                "sorry_count": len(pending),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


# ---------------------------------------------------------------------------
# Test: full pipeline with Phase 4 COMPLETE
# ---------------------------------------------------------------------------

def test_phase5_full_pipeline_complete(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    monkeypatch.setattr(
        phase5,
        "_run_deerflow_agent",
        lambda *_args, **_kwargs: json.dumps(
            {
                "warning_review": "No issues found.",
                "redundancy_notes": "All code is concise.",
                "extractable_lemmas": [],
                "recommendations": ["Project is ready for publication."],
                "changes_applied": False,
            }
        ),
    )

    # Mock subprocess.run for compile check
    class FakeCompletedProcess:
        returncode = 0
        stdout = "Build completed successfully.\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeCompletedProcess)

    state = _base_state("thread-phase5-complete", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    state["outputs_root"] = str(tmp_path / "outputs")
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_phase4_workspace(
        project_root,
        stage="COMPLETE",
        pending=[],
        completed=["formal/src/Main.lean", "formal/src/Helpers.lean"],
    )

    # Add lakefile so compile check can run
    (project_root / "formal" / "lakefile.lean").write_text("import Lake\nopen Lake DSL\npackage test\n")

    state = phase5.phase4_sync_node(state)
    state = phase5.final_sorry_axiom_check_node(state)
    state = phase5.compile_check_node(state)
    state = phase5.polish_agent_node(state)
    state = phase5.artifact_pack_node(state)
    state = phase5.export_outputs_node(state)
    state = phase5.runtime_history_align_node(state)
    state = phase5.manifest_node(state)

    assert state["stage"] == "MANIFEST_READY"
    assert state["phase4_stage"] == "COMPLETE"
    assert state["sorry_axiom_pass"] is True
    assert state["total_sorry_count"] == 0
    assert state["total_axiom_count"] == 0
    assert state["compile_pass"] is True

    # Verify outputs (manifests exported before manifest_node runs)
    outputs = Path(state["outputs_root"])
    assert (outputs / f"{state['project_name']}_phase5_summary.json").exists()
    assert (outputs / "manifests" / "phase5_sync.json").exists()
    assert (outputs / "manifests" / "phase5_sorry_axiom_check.json").exists()
    assert (outputs / "manifests" / "phase5_compile_check.json").exists()

    # Verify proof journal
    journal = json.loads((project_root / "journal" / "proof_journal.json").read_text())
    assert journal["final_verdict"] == "PASS"
    assert journal["phases"]["phase5_polish"]["sorry_axiom_pass"] is True

    # Verify final manifest
    manifest = json.loads((project_root / "manifests" / "phase5_polish.json").read_text())
    assert manifest["phase"] == "phase5_polish"
    assert manifest["next"] is None
    assert manifest["results"]["sorry_axiom_check"]["pass"] is True


# ---------------------------------------------------------------------------
# Test: handles Phase 4 FAILED state
# ---------------------------------------------------------------------------

def test_phase5_handles_phase4_failure(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    monkeypatch.setattr(
        phase5,
        "_run_deerflow_agent",
        lambda *_args, **_kwargs: json.dumps(
            {
                "warning_review": "Unfinished project.",
                "redundancy_notes": "",
                "extractable_lemmas": [],
                "recommendations": ["Remaining sorries need manual attention."],
                "changes_applied": False,
            }
        ),
    )

    class FakeFailedProcess:
        returncode = 1
        stdout = ""
        stderr = "error: unsolved goals\nMain.lean:2:8: warning: unused variable x\n"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeFailedProcess)

    state = _base_state("thread-phase5-fail", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    state["outputs_root"] = str(tmp_path / "outputs")
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    _prepare_phase4_workspace(
        project_root,
        stage="FAILED",
        pending=["formal/src/Main.lean"],
        completed=["formal/src/Helpers.lean"],
    )
    (project_root / "formal" / "lakefile.lean").write_text("import Lake\nopen Lake DSL\npackage test\n")

    state = phase5.phase4_sync_node(state)
    state = phase5.final_sorry_axiom_check_node(state)
    state = phase5.compile_check_node(state)
    state = phase5.polish_agent_node(state)
    state = phase5.artifact_pack_node(state)
    state = phase5.export_outputs_node(state)
    state = phase5.runtime_history_align_node(state)
    state = phase5.manifest_node(state)

    assert state["stage"] == "MANIFEST_READY"
    assert state["phase4_stage"] == "FAILED"
    assert state["sorry_axiom_pass"] is False
    assert state["total_sorry_count"] == 1
    assert state["compile_pass"] is False
    assert len(state["compile_warnings"]) == 1

    journal = json.loads((project_root / "journal" / "proof_journal.json").read_text())
    assert journal["final_verdict"] == "FAIL"

    manifest = json.loads((project_root / "manifests" / "phase5_polish.json").read_text())
    assert manifest["results"]["sorry_axiom_check"]["total_sorry"] == 1


# ---------------------------------------------------------------------------
# Test: sorry/axiom detection at line level
# ---------------------------------------------------------------------------

def test_phase5_sorry_axiom_check_detects_sorries(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-phase5-detect", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]

    src_dir = project_root / "formal" / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)

    # Write files with various sorry/axiom patterns
    (src_dir / "A.lean").write_text("import Mathlib\n\ntheorem t1 : True := by\n  sorry\n\naxiom bad : False\n")
    (src_dir / "B.lean").write_text("import Mathlib\n\ntheorem t2 : True := by\n  trivial\n")
    (src_dir / "Sub").mkdir(parents=True, exist_ok=True)
    (src_dir / "Sub" / "C.lean").write_text("lemma l1 : 1 = 1 := rfl\n")

    state["module_files"] = [
        "formal/src/A.lean",
        "formal/src/B.lean",
        "formal/src/Sub/C.lean",
    ]

    state = phase5.final_sorry_axiom_check_node(state)

    assert state["sorry_axiom_pass"] is False
    assert state["total_sorry_count"] == 1
    assert state["total_axiom_count"] == 1

    report = state["sorry_axiom_report"]
    per_file = {entry["file"]: entry for entry in report["per_file"]}
    assert per_file["formal/src/A.lean"]["sorry_count"] == 1
    assert per_file["formal/src/A.lean"]["axiom_count"] == 1
    assert per_file["formal/src/A.lean"]["sorry_lines"] == [4]
    assert per_file["formal/src/B.lean"]["sorry_count"] == 0
    assert per_file["formal/src/B.lean"]["axiom_count"] == 0
    assert per_file["formal/src/Sub/C.lean"]["sorry_count"] == 0

    assert (project_root / "manifests" / "phase5_sorry_axiom_check.json").exists()


# ---------------------------------------------------------------------------
# Test: compile check captures errors and warnings
# ---------------------------------------------------------------------------

def test_phase5_compile_check_captures_errors(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    class FakeErrorProcess:
        returncode = 1
        stdout = ""
        stderr = "error: type mismatch\nwarning: unused variable 'h'\nerror: unknown identifier\n"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeErrorProcess)

    state = _base_state("thread-phase5-compile", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    (project_root / "formal").mkdir(parents=True, exist_ok=True)
    (project_root / "formal" / "lakefile.lean").write_text("import Lake\nopen Lake DSL\npackage test\n")
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)

    state = phase5.compile_check_node(state)

    assert state["compile_pass"] is False
    assert len(state["compile_warnings"]) == 1
    assert "warning: unused variable 'h'" in state["compile_warnings"]
    assert (project_root / "manifests" / "phase5_compile_check.json").exists()


# ---------------------------------------------------------------------------
# Test: compile check handles missing lake gracefully
# ---------------------------------------------------------------------------

def test_phase5_compile_check_handles_missing_lake(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("lake")))

    state = _base_state("thread-phase5-no-lake", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    (project_root / "formal").mkdir(parents=True, exist_ok=True)
    (project_root / "formal" / "lakefile.lean").write_text("import Lake\nopen Lake DSL\npackage test\n")
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)

    state = phase5.compile_check_node(state)

    assert state["compile_pass"] is False
    assert "lake command not found" in state["compile_check_report"]["stderr"]


# ---------------------------------------------------------------------------
# Test: polish agent fallback on unparseable output
# ---------------------------------------------------------------------------

def test_phase5_polish_agent_fallback_on_bad_json(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(phase5, "_run_deerflow_agent", lambda *_args, **_kwargs: "not json at all ---")

    state = _base_state("thread-phase5-bad-json", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    (project_root / "formal" / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    (project_root / "formal" / "src" / "Test.lean").write_text("theorem t : True := by\n  trivial\n")
    state["compile_warnings"] = []
    state["sorry_axiom_report"] = {"pass": True}

    state = phase5.polish_agent_node(state)

    assert state["stage"] == "POLISHED"
    assert state["polish_report"]["warning_review"] == "Could not parse polish agent output."
    assert state["polish_recommendations"] == ["Manual review recommended."]
    assert state["polish_changes_applied"] is False
    assert (project_root / "manifests" / "phase5_polish_report.json").exists()


# ---------------------------------------------------------------------------
# Test: export creates outputs correctly
# ---------------------------------------------------------------------------

def test_phase5_export_creates_outputs(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-phase5-export", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    state["outputs_root"] = str(tmp_path / "outputs")
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]

    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    (project_root / "journal").mkdir(parents=True, exist_ok=True)
    (project_root / "formal").mkdir(parents=True, exist_ok=True)
    (project_root / "scratch").mkdir(parents=True, exist_ok=True)

    # Create some manifest files to export
    (project_root / "manifests" / "phase5_sync.json").write_text(json.dumps({"test": 1}))
    (project_root / "manifests" / "phase5_sorry_axiom_check.json").write_text(json.dumps({"test": 2}))
    (project_root / "journal" / "session_notes.md").write_text("# Notes\nTest journal.")

    # Create a minimal .tar.gz for the archive
    import tarfile
    archive_path = project_root / "scratch" / "demo_formal_002.tar.gz"
    with tarfile.open(str(archive_path), "w:gz") as tar:
        (project_root / "formal" / "README.md").write_text("# Formal\n")
        tar.add(str(project_root / "formal"), arcname="formal")

    state["artifact_archive_path"] = f"{state['project_root']}/scratch/demo_formal_002.tar.gz"
    state["sorry_axiom_pass"] = True
    state["compile_pass"] = True
    state["extractable_lemmas"] = []
    state["polish_recommendations"] = []
    state["total_sorry_count"] = 0
    state["total_axiom_count"] = 0
    state["compile_warnings"] = []
    state["phase4_stage"] = "COMPLETE"
    state["exported_paths"] = []

    state = phase5.export_outputs_node(state)

    assert state["stage"] == "EXPORTED"
    assert len(state["exported_paths"]) >= 4  # archive + 2 manifests + journal + summary

    outputs = Path(state["outputs_root"])
    assert (outputs / "demo_formal_002.tar.gz").exists()
    assert (outputs / "manifests" / "phase5_sync.json").exists()
    assert (outputs / "manifests" / "phase5_sorry_axiom_check.json").exists()
    assert (outputs / "journal" / "session_notes.md").exists()
    assert (outputs / f"{state['project_name']}_phase5_summary.json").exists()
    assert (project_root / "manifests" / "phase5_export_report.json").exists()


# ---------------------------------------------------------------------------
# Test: final manifest contains all results
# ---------------------------------------------------------------------------

def test_phase5_manifest_generated(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-phase5-manifest", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)

    state["phase4_stage"] = "COMPLETE"
    state["sorry_axiom_pass"] = True
    state["total_sorry_count"] = 0
    state["total_axiom_count"] = 0
    state["compile_pass"] = True
    state["compile_warnings"] = []
    state["polish_changes_applied"] = True
    state["extractable_lemmas"] = ["lemma_helper"]
    state["polish_recommendations"] = ["Ready to publish.", "Consider adding docs."]
    state["exported_paths"] = ["/tmp/o1", "/tmp/o2"]

    state = phase5.manifest_node(state)

    assert state["stage"] == "MANIFEST_READY"

    manifest = json.loads((project_root / "manifests" / "phase5_polish.json").read_text())
    assert manifest["phase"] == "phase5_polish"
    assert manifest["next"] is None
    assert len(manifest["stages"]) == 7
    assert manifest["results"]["sorry_axiom_check"]["pass"] is True
    assert manifest["results"]["compile_check"]["pass"] is True
    assert manifest["results"]["polish"]["changes_applied"] is True
    assert manifest["results"]["polish"]["extractable_lemmas"] == ["lemma_helper"]
    assert manifest["results"]["export"]["export_count"] == 2
    assert manifest["summary"]["sorry_axiom_check"]["pass"] is True


def test_phase5_runtime_history_alignment_consumes_thread_runtime_log(tmp_path, monkeypatch):
    phase1, phase5 = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    state = _base_state("thread-phase5-history", "demo")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    project_root = Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"]) / "threads" / state["thread_id"] / "user-data" / "workspace" / state["project_name"]
    (project_root / "journal").mkdir(parents=True, exist_ok=True)
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    (project_root / "manifests" / "phase3_archon_scaffolding.json").write_text(
        json.dumps({"stage": "MANIFEST_READY", "module_files": ["formal/src/Main.lean"], "sorry_count": 0})
    )

    phase1.log_runtime_event(state["thread_id"], "phase4_archon_proving", "plan_agent", {"focus_files": ["formal/src/Main.lean"]})
    phase1.log_runtime_event(state["thread_id"], "phase4_archon_proving", "review_agent", {"stage": "COMPLETE"})

    state["phase4_stage"] = "COMPLETE"
    state["phase4_loop_count"] = 1
    state["phase4_pending"] = []
    state["phase4_completed"] = ["formal/src/Main.lean"]
    state["phase4_failure_modes"] = []
    state["sorry_axiom_pass"] = True
    state["compile_pass"] = True
    state["extractable_lemmas"] = []

    state = phase5.runtime_history_align_node(state)

    assert state["stage"] == "HISTORY_ALIGNED"
    assert any(entry.get("phase") == "phase4_archon_proving" for entry in state["deerflow_history_entries"])
    assert (project_root / "journal" / "deerflow_history_alignment.json").exists()
