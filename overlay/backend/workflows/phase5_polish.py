"""
Phase 5 — Polish / Export / Runtime History (DeerFlow-native).

Terminal stage of the Archon + Rethlas pipeline:
  - bridge Phase 4 state (COMPLETE or FAILED)
  - final sorry / axiom scan across all .lean files
  - compile check (lake build)
  - LLM-driven polish review (warnings, redundancy, extractable lemmas)
  - artifact packaging (.tar.gz)
  - output export to /mnt/user-data/outputs
  - cross-phase runtime history alignment
  - final manifest generation
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
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
    read_runtime_history,
)
from .phase3_archon_scaffolding import _extract_json_object, _run_deerflow_agent
from .phase4_archon_proving import (
    _append_jsonl,
    _host_project_root,
    _load_json,
    _read_text,
)


class Phase5PolishState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    project_name: str
    stage: Literal[
        "BOOTSTRAP",
        "PHASE4_SYNC",
        "SORRY_AXIOM_CHECKED",
        "COMPILE_CHECKED",
        "POLISHED",
        "ARTIFACT_PACKED",
        "EXPORTED",
        "HISTORY_ALIGNED",
        "MANIFEST_READY",
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

    # Phase 4 bridge
    phase4_manifest: dict
    phase4_stage: str
    phase4_loop_count: int
    phase4_pending: list[str]
    phase4_completed: list[str]
    phase4_failure_modes: list[dict]

    # Module tracking
    module_files: list[str]

    # Sorry / axiom check
    sorry_axiom_report: dict
    total_sorry_count: int
    total_axiom_count: int
    sorry_axiom_pass: bool

    # Compile check
    compile_check_report: dict
    compile_pass: bool
    compile_warnings: list[str]

    # Polish agent
    polish_report: dict
    warning_review: str
    redundancy_notes: str
    extractable_lemmas: list[str]
    polish_recommendations: list[str]
    polish_changes_applied: bool

    # Artifact packing
    artifact_archive_path: str
    artifact_manifest: dict

    # Export
    export_report: dict
    exported_paths: list[str]

    # Runtime history alignment
    proof_journal: dict
    deerflow_history_entries: list[dict]

    artifacts: Annotated[list[str], merge_artifacts]


def _generate_summary_report(state: Phase5PolishState) -> dict:
    return {
        "project_name": state.get("project_name", ""),
        "thread_id": state.get("thread_id", ""),
        "phase4_stage": state.get("phase4_stage", "UNKNOWN"),
        "sorry_axiom_check": {
            "pass": state.get("sorry_axiom_pass", False),
            "total_sorry": state.get("total_sorry_count", -1),
            "total_axiom": state.get("total_axiom_count", -1),
        },
        "compile_check": {
            "pass": state.get("compile_pass", False),
            "warnings": len(state.get("compile_warnings", [])),
        },
        "polish": {
            "extractable_lemmas": len(state.get("extractable_lemmas", [])),
            "recommendations": len(state.get("polish_recommendations", [])),
        },
        "artifact": {
            "archive": state.get("artifact_archive_path", ""),
            "exported_file_count": len(state.get("exported_paths", [])),
        },
    }


# ---------------------------------------------------------------------------
# Node: phase4_sync_node
# ---------------------------------------------------------------------------

def phase4_sync_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)

    manifest_path = project_root / "manifests" / "phase4_archon_proving.json"
    manifest = _load_json(manifest_path, {})

    module_files = manifest.get("pending", []) + manifest.get("completed", [])
    if not module_files:
        formal_src = project_root / "formal" / "src"
        if formal_src.exists():
            module_files = sorted(
                str(p.relative_to(project_root))
                for p in formal_src.rglob("*.lean")
            )

    phase4_stage = manifest.get("stage", "UNKNOWN")

    sync_record = {
        "phase": "phase5_polish",
        "bridge_source": "phase4_archon_proving",
        "phase4_stage": phase4_stage,
        "module_files_count": len(module_files),
        "pending_count": len(manifest.get("pending", [])),
        "completed_count": len(manifest.get("completed", [])),
    }
    sync_path = project_root / "manifests" / "phase5_sync.json"
    sync_path.write_text(json.dumps(sync_record, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "phase4_sync",
        {
            "phase4_stage": phase4_stage,
            "module_files_count": len(module_files),
        },
    )

    return {
        **state,
        "stage": "PHASE4_SYNC",
        "phase4_manifest": manifest,
        "phase4_stage": phase4_stage,
        "phase4_loop_count": manifest.get("loop_count", 0),
        "phase4_pending": manifest.get("pending", []),
        "phase4_completed": manifest.get("completed", []),
        "phase4_failure_modes": manifest.get("failure_modes", []),
        "module_files": module_files,
        "artifacts": [f"{project_name}/manifests/phase5_sync.json"],
    }


# ---------------------------------------------------------------------------
# Node: final_sorry_axiom_check_node
# ---------------------------------------------------------------------------

def final_sorry_axiom_check_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    module_files = state.get("module_files", [])
    formal_src = project_root / "formal" / "src"

    per_file: list[dict] = []
    total_sorry = 0
    total_axiom = 0

    files_to_scan = []
    if module_files:
        files_to_scan = [
            (project_root / mf) for mf in module_files if (project_root / mf).exists()
        ]
    elif formal_src.exists():
        files_to_scan = sorted(formal_src.rglob("*.lean"))

    for lean_file in files_to_scan:
        try:
            content = lean_file.read_text()
            lines = content.splitlines()
        except Exception:
            continue

        sorry_lines = []
        axiom_lines = []
        for i, line in enumerate(lines, start=1):
            if "sorry" in line:
                sorry_lines.append(i)
            if "axiom" in line:
                axiom_lines.append(i)

        rel = str(lean_file.relative_to(project_root))
        per_file.append(
            {
                "file": rel,
                "sorry_count": len(sorry_lines),
                "sorry_lines": sorry_lines,
                "axiom_count": len(axiom_lines),
                "axiom_lines": axiom_lines,
            }
        )
        total_sorry += len(sorry_lines)
        total_axiom += len(axiom_lines)

    pass_ = total_sorry == 0 and total_axiom == 0

    report = {
        "phase": "phase5_polish",
        "stage": "sorry_axiom_check",
        "pass": pass_,
        "total_sorry_count": total_sorry,
        "total_axiom_count": total_axiom,
        "per_file": per_file,
    }
    report_path = project_root / "manifests" / "phase5_sorry_axiom_check.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "final_sorry_axiom_check",
        {
            "pass": pass_,
            "total_sorry_count": total_sorry,
            "total_axiom_count": total_axiom,
        },
    )

    return {
        **state,
        "stage": "SORRY_AXIOM_CHECKED",
        "sorry_axiom_report": report,
        "total_sorry_count": total_sorry,
        "total_axiom_count": total_axiom,
        "sorry_axiom_pass": pass_,
        "artifacts": [f"{project_name}/manifests/phase5_sorry_axiom_check.json"],
    }


# ---------------------------------------------------------------------------
# Node: compile_check_node
# ---------------------------------------------------------------------------

def compile_check_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    formal_dir = project_root / "formal"

    has_lakefile = (formal_dir / "lakefile.lean").exists() or (formal_dir / "lakefile.toml").exists()

    if not has_lakefile:
        report = {
            "phase": "phase5_polish",
            "stage": "compile_check",
            "pass": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "No lakefile found in formal/ directory.",
            "warnings": [],
        }
    else:
        try:
            result = subprocess.run(
                ["lake", "build"],
                cwd=str(formal_dir),
                capture_output=True,
                text=True,
                timeout=300,
            )
            returncode = result.returncode
            stdout = result.stdout or ""
            stderr = result.stderr or ""
        except subprocess.TimeoutExpired:
            returncode = -1
            stdout = ""
            stderr = "lake build timed out after 300 seconds."
        except FileNotFoundError:
            returncode = -1
            stdout = ""
            stderr = "lake command not found on PATH."
        except Exception as exc:
            returncode = -1
            stdout = ""
            stderr = f"Unexpected error: {exc}"

        pass_ = returncode == 0

        warnings = [
            line.strip()
            for line in stderr.splitlines()
            if "warning" in line.lower()
        ]

        report = {
            "phase": "phase5_polish",
            "stage": "compile_check",
            "pass": pass_,
            "returncode": returncode,
            "stdout": stdout[:2000],
            "stderr": stderr[:2000],
            "warnings": warnings[:50],
        }

    report_path = project_root / "manifests" / "phase5_compile_check.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "compile_check",
        {
            "pass": report["pass"],
            "returncode": report.get("returncode", -1),
            "warning_count": len(report.get("warnings", [])),
        },
    )

    return {
        **state,
        "stage": "COMPILE_CHECKED",
        "compile_check_report": report,
        "compile_pass": report["pass"],
        "compile_warnings": report.get("warnings", []),
        "artifacts": [f"{project_name}/manifests/phase5_compile_check.json"],
    }


# ---------------------------------------------------------------------------
# Node: polish_agent_node
# ---------------------------------------------------------------------------

def polish_agent_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    compile_warnings = state.get("compile_warnings", [])
    sorry_axiom_report = state.get("sorry_axiom_report", {})

    formal_src = project_root / "formal" / "src"
    file_snippets: list[dict] = []
    for lean_file in sorted(formal_src.rglob("*.lean")):
        rel = str(lean_file.relative_to(project_root))
        content = _read_text(lean_file)
        file_snippets.append(
            {
                "file": rel,
                "length": len(content),
                "preview": content[:500],
            }
        )

    system_prompt = (
        "You are the Archon polish agent.\n"
        "Your role is to review a completed Lean 4 formalization project and identify:\n"
        "1. Any remaining warnings or style issues in the Lean code\n"
        "2. Redundant code patterns that should be simplified\n"
        "3. Extractable lemmas that could be factored out for reuse\n"
        "4. General recommendations for improvement\n\n"
        "The project has already been compiled with `lake build`. Provide a polish review.\n"
        "Return compact JSON with keys: warning_review, redundancy_notes, "
        "extractable_lemmas (list), recommendations (list), changes_applied (bool)."
    )

    prompt = (
        f"Project: {project_name}\n\n"
        f"Compile warnings ({len(compile_warnings)}):\n"
        + ("\n".join(compile_warnings[:20]) if compile_warnings else "(none)")
        + "\n\n"
        f"Sorry/Axiom check: {sorry_axiom_report.get('pass', 'unknown')}\n"
        f"Files ({len(file_snippets)}):\n"
        + json.dumps(file_snippets[:15], ensure_ascii=False, indent=2)
        + "\n\nReview the project. Return JSON only."
    )

    raw = _run_deerflow_agent(
        prompt,
        system_prompt=system_prompt,
        tools=[],
        thread_id=f"{thread_id}-archon-polish",
    )
    try:
        parsed = _extract_json_object(raw)
    except Exception:
        parsed = {
            "warning_review": "Could not parse polish agent output.",
            "redundancy_notes": "No redundancy analysis available.",
            "extractable_lemmas": [],
            "recommendations": ["Manual review recommended."],
            "changes_applied": False,
        }

    report_path = project_root / "manifests" / "phase5_polish_report.json"
    report_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "polish_agent",
        {
            "changes_applied": parsed.get("changes_applied", False),
            "extractable_lemmas": len(parsed.get("extractable_lemmas", [])),
        },
    )

    return {
        **state,
        "stage": "POLISHED",
        "polish_report": parsed,
        "warning_review": parsed.get("warning_review", ""),
        "redundancy_notes": parsed.get("redundancy_notes", ""),
        "extractable_lemmas": parsed.get("extractable_lemmas", []),
        "polish_recommendations": parsed.get("recommendations", []),
        "polish_changes_applied": parsed.get("changes_applied", False),
        "artifacts": [f"{project_name}/manifests/phase5_polish_report.json"],
    }


# ---------------------------------------------------------------------------
# Node: artifact_pack_node
# ---------------------------------------------------------------------------

def artifact_pack_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    formal_dir = project_root / "formal"
    scratch_dir = project_root / "scratch"

    if not formal_dir.exists():
        return {
            **state,
            "stage": "ARTIFACT_PACKED",
            "artifact_archive_path": "",
            "artifact_manifest": {
                "phase": "phase5_polish",
                "stage": "artifact_pack",
                "error": "formal/ directory does not exist.",
                "archive_path": "",
            },
            "artifacts": state.get("artifacts", []),
        }

    archive_name = f"{project_name}_formal_{state.get('phase4_loop_count', 0):03d}.tar.gz"
    archive_path = scratch_dir / archive_name
    try:
        with tarfile.open(str(archive_path), "w:gz") as tar:
            tar.add(str(formal_dir), arcname=formal_dir.name)
        artifact_rel = f"{state['project_root']}/scratch/{archive_name}"
    except Exception as exc:
        artifact_rel = ""
        manifest = {
            "phase": "phase5_polish",
            "stage": "artifact_pack",
            "error": str(exc),
            "archive_path": "",
        }
        manifest_path = project_root / "manifests" / "phase5_artifact_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        return {
            **state,
            "stage": "ARTIFACT_PACKED",
            "artifact_archive_path": "",
            "artifact_manifest": manifest,
            "artifacts": [f"{project_name}/manifests/phase5_artifact_manifest.json"],
        }

    manifest = {
        "phase": "phase5_polish",
        "stage": "artifact_pack",
        "archive_path": artifact_rel,
        "includes": ["formal/"],
        "compression": "gzip",
        "format": "tar",
    }
    manifest_path = project_root / "manifests" / "phase5_artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "artifact_pack",
        {
            "archive_path": artifact_rel,
            "includes": manifest.get("includes", []),
        },
    )

    return {
        **state,
        "stage": "ARTIFACT_PACKED",
        "artifact_archive_path": artifact_rel,
        "artifact_manifest": manifest,
        "artifacts": [f"{project_name}/manifests/phase5_artifact_manifest.json"],
    }


# ---------------------------------------------------------------------------
# Node: export_outputs_node
# ---------------------------------------------------------------------------

def export_outputs_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    outputs_root = Path(state.get("outputs_root") or "/mnt/user-data/outputs")
    manifests_root = project_root / "manifests"
    journal_root = project_root / "journal"

    outputs_root.mkdir(parents=True, exist_ok=True)

    export_map: list[dict[str, str]] = []
    exported_paths: list[str] = []

    # 1. Artifact archive
    archive_rel = state.get("artifact_archive_path", "")
    if archive_rel:
        archive_abs = project_root / Path(archive_rel).relative_to(state["project_root"]) if archive_rel.startswith(state["project_root"]) else Path(archive_rel)
        if archive_abs.exists():
            dst = outputs_root / archive_abs.name
            shutil.copy2(str(archive_abs), str(dst))
            export_map.append(
                {"source": str(archive_abs), "destination": str(dst), "type": "archive"}
            )
            exported_paths.append(str(dst))

    # 2. Phase 5 manifests
    if manifests_root.exists():
        dst_dir = outputs_root / "manifests"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for manifest_file in sorted(manifests_root.glob("phase5_*.json")):
            dst = dst_dir / manifest_file.name
            shutil.copy2(str(manifest_file), str(dst))
            export_map.append(
                {
                    "source": str(manifest_file),
                    "destination": str(dst),
                    "type": "manifest",
                }
            )
            exported_paths.append(str(dst))

    # 3. Proof journal
    if journal_root.exists():
        dst_dir = outputs_root / "journal"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for journal_file in journal_root.rglob("*"):
            if journal_file.is_file():
                rel = journal_file.relative_to(journal_root)
                dst = dst_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(journal_file), str(dst))
                export_map.append(
                    {
                        "source": str(journal_file),
                        "destination": str(dst),
                        "type": "journal",
                    }
                )
                exported_paths.append(str(dst))

    # 4. Summary report
    summary = _generate_summary_report(state)
    summary_path = outputs_root / f"{project_name}_phase5_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    export_map.append(
        {"source": "inline", "destination": str(summary_path), "type": "summary"}
    )
    exported_paths.append(str(summary_path))

    report = {
        "phase": "phase5_polish",
        "stage": "export",
        "outputs_root": str(outputs_root),
        "export_count": len(export_map),
        "exports": export_map,
    }
    export_manifest_path = project_root / "manifests" / "phase5_export_report.json"
    export_manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "export_outputs",
        {
            "outputs_root": str(outputs_root),
            "export_count": len(export_map),
        },
    )

    return {
        **state,
        "stage": "EXPORTED",
        "export_report": report,
        "exported_paths": exported_paths,
        "artifacts": [f"{project_name}/manifests/phase5_export_report.json"],
    }


# ---------------------------------------------------------------------------
# Node: runtime_history_align_node
# ---------------------------------------------------------------------------

def runtime_history_align_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    journal_dir = project_root / "journal"

    phase3_manifest = _load_json(
        project_root / "manifests" / "phase3_archon_scaffolding.json", {}
    )

    journal = {
        "thread_id": thread_id,
        "project_name": project_name,
        "phases": {
            "phase3_archon_scaffolding": {
                "stage": phase3_manifest.get("stage", "unknown"),
                "module_count": len(phase3_manifest.get("module_files", [])),
                "sorry_count": phase3_manifest.get("sorry_count", 0),
            },
            "phase4_archon_proving": {
                "stage": state.get("phase4_stage", "unknown"),
                "loop_count": state.get("phase4_loop_count", 0),
                "pending_files": state.get("phase4_pending", []),
                "completed_files": state.get("phase4_completed", []),
                "failure_modes": state.get("phase4_failure_modes", [])[-5:],
            },
            "phase5_polish": {
                "sorry_axiom_pass": state.get("sorry_axiom_pass", False),
                "compile_pass": state.get("compile_pass", False),
                "extractable_lemmas": state.get("extractable_lemmas", []),
            },
        },
        "final_verdict": (
            "PASS"
            if state.get("sorry_axiom_pass") and state.get("compile_pass")
            else (
                "PASS_WITH_WARNINGS"
                if state.get("sorry_axiom_pass")
                else "FAIL"
            )
        ),
        "summary": _generate_summary_report(state),
    }

    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_path = journal_dir / "proof_journal.json"
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2))

    runtime_history = read_runtime_history(thread_id)
    history_entries = runtime_history + [
        {
            "timestamp": "",
            "thread_id": thread_id,
            "phase": "phase3_archon_scaffolding",
            "node": "phase3_manifest_bridge",
            "payload": {
                "stage": phase3_manifest.get("stage", "unknown"),
                "module_count": len(phase3_manifest.get("module_files", [])),
                "sorry_count": phase3_manifest.get("sorry_count", 0),
            },
        }
    ]

    history_path = journal_dir / "deerflow_history_alignment.json"
    history_path.write_text(json.dumps(history_entries, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "runtime_history_align",
        {
            "runtime_event_count": len(runtime_history),
            "history_alignment_count": len(history_entries),
        },
    )

    return {
        **state,
        "stage": "HISTORY_ALIGNED",
        "proof_journal": journal,
        "deerflow_history_entries": history_entries,
        "artifacts": [
            f"{project_name}/journal/proof_journal.json",
            f"{project_name}/journal/deerflow_history_alignment.json",
        ],
    }


# ---------------------------------------------------------------------------
# Node: manifest_node
# ---------------------------------------------------------------------------

def manifest_node(state: Phase5PolishState) -> Phase5PolishState:
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)

    manifest = {
        "phase": "phase5_polish",
        "project_name": project_name,
        "thread_id": thread_id,
        "stages": [
            "phase4_sync",
            "final_sorry_axiom_check",
            "compile_check",
            "polish_agent",
            "artifact_pack",
            "export_outputs",
            "runtime_history_align",
        ],
        "results": {
            "phase4_bridge": {
                "source_phase": "phase4_archon_proving",
                "phase4_stage": state.get("phase4_stage", "UNKNOWN"),
            },
            "sorry_axiom_check": {
                "pass": state.get("sorry_axiom_pass", False),
                "total_sorry": state.get("total_sorry_count", 0),
                "total_axiom": state.get("total_axiom_count", 0),
            },
            "compile_check": {
                "pass": state.get("compile_pass", False),
                "warning_count": len(state.get("compile_warnings", [])),
            },
            "polish": {
                "changes_applied": state.get("polish_changes_applied", False),
                "extractable_lemmas": state.get("extractable_lemmas", []),
                "recommendations": state.get("polish_recommendations", [])[:5],
            },
            "export": {
                "outputs_root": state.get("outputs_root", ""),
                "export_count": len(state.get("exported_paths", [])),
            },
        },
        "summary": _generate_summary_report(state),
        "next": None,
    }

    manifest_path = project_root / "manifests" / "phase5_polish.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    log_runtime_event(
        thread_id,
        "phase5_polish",
        "manifest",
        {
            "stage": "MANIFEST_READY",
            "compile_pass": state.get("compile_pass", False),
            "sorry_axiom_pass": state.get("sorry_axiom_pass", False),
        },
    )

    return {
        **state,
        "stage": "MANIFEST_READY",
        "artifacts": [f"{project_name}/manifests/phase5_polish.json"],
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def route_after_manifest(state: Phase5PolishState) -> str:
    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_phase5_polish_graph():
    graph = StateGraph(Phase5PolishState)

    graph.add_node("bootstrap_layout", bootstrap_layout)
    graph.add_node("phase4_sync", phase4_sync_node)
    graph.add_node("final_sorry_axiom_check", final_sorry_axiom_check_node)
    graph.add_node("compile_check", compile_check_node)
    graph.add_node("polish_agent", polish_agent_node)
    graph.add_node("artifact_pack", artifact_pack_node)
    graph.add_node("export_outputs", export_outputs_node)
    graph.add_node("runtime_history_align", runtime_history_align_node)
    graph.add_node("manifest", manifest_node)

    graph.set_entry_point("bootstrap_layout")
    graph.add_edge("bootstrap_layout", "phase4_sync")
    graph.add_edge("phase4_sync", "final_sorry_axiom_check")
    graph.add_edge("final_sorry_axiom_check", "compile_check")
    graph.add_edge("compile_check", "polish_agent")
    graph.add_edge("polish_agent", "artifact_pack")
    graph.add_edge("artifact_pack", "export_outputs")
    graph.add_edge("export_outputs", "runtime_history_align")
    graph.add_edge("runtime_history_align", "manifest")
    graph.add_conditional_edges("manifest", route_after_manifest, {END: END})

    return graph.compile(checkpointer=_memory_checkpointer())


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run_phase5_polish_workflow(
    thread_id: str,
    project_name: str = "project",
) -> dict:
    return build_phase5_polish_graph().invoke(
        {
            "messages": [],
            "thread_id": thread_id,
            "project_name": project_name,
            "stage": "BOOTSTRAP",
            # layout
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
            # phase4 bridge
            "phase4_manifest": {},
            "phase4_stage": "",
            "phase4_loop_count": 0,
            "phase4_pending": [],
            "phase4_completed": [],
            "phase4_failure_modes": [],
            "module_files": [],
            # sorry/axiom
            "sorry_axiom_report": {},
            "total_sorry_count": 0,
            "total_axiom_count": 0,
            "sorry_axiom_pass": False,
            # compile
            "compile_check_report": {},
            "compile_pass": False,
            "compile_warnings": [],
            # polish
            "polish_report": {},
            "warning_review": "",
            "redundancy_notes": "",
            "extractable_lemmas": [],
            "polish_recommendations": [],
            "polish_changes_applied": False,
            # artifact
            "artifact_archive_path": "",
            "artifact_manifest": {},
            # export
            "export_report": {},
            "exported_paths": [],
            # history
            "proof_journal": {},
            "deerflow_history_entries": [],
            # standard
            "artifacts": [],
        },
        {"configurable": {"thread_id": thread_id}},
    )
