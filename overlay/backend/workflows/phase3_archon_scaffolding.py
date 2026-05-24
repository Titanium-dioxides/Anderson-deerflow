"""
Phase 3 — Archon Scaffolding (DeerFlow-native).

Bridges Phase 2 Rethlas informal proof output into an Archon-style Lean 4
project skeleton:
  - references ingestion and structuring
  - formal project initialization (lake + .archon/ state directory)
  - auto-formalize: informal proof -> Lean theorem/definition skeletons (sorry'd)
  - file splitting (theorem modules, lemma helpers)
  - manifests / journal generation

This phase preserves the Archon paper/design: plan-agent orchestration,
prover-agent autoformalize stage, and the .archon/ state-file contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from .phase1_runtime import _memory_checkpointer, _runtime_root, bootstrap_layout, merge_artifacts

# ---------------------------------------------------------------------------
# Archon template files (inlined from Archon/.archon-src/archon-template/)
# ---------------------------------------------------------------------------

ARCHON_PROGRESS_TEMPLATE = """\
# Project Progress

## Current Stage
autoformalize

## Stages
- [ ] autoformalize
- [ ] prover
- [ ] polish

## Current Objectives
"""

ARCHON_TASK_PENDING_TEMPLATE = """\
# Index
<!-- One line per file. Update line numbers when the file changes. -->

---
"""

ARCHON_USER_HINTS_TEMPLATE = """\
# User Hints

Write strategic guidance here. The plan agent reads this file every iteration.
Provers do not read this file — the plan agent translates your hints into concrete objectives.

<!-- Example: "The measure_union approach is a dead end. Try sigma-additivity instead." -->
<!-- Example: "Focus on Algebra/WLocal.lean first — the rest depends on it." -->
"""

ARCHON_CLAUDE_TEMPLATE = """\
# Archon Project

You are either the plan agent, a prover agent, or the review agent.
Read `PROGRESS.md` to determine your role and current objectives.
Keep workspace tidy. Prefer existing MCP tools.

## Priority Rule
If instructions conflict between global and local sources, **local takes precedence**.

## Key Files & Permissions
All state files are in `.archon/`:

| File | Plan Agent | Prover Agent | Review Agent | User |
|------|-----------|-------------|-------------|------|
| `.archon/PROGRESS.md` | read + write | **read only** | read only | read |
| `.archon/USER_HINTS.md` | read (then clear) | do not read | do not read | write |
| `.archon/task_pending.md` | read + write | **read only** | read only | read |
| `.archon/task_done.md` | read + write | **read only** | read only | read |
| `.archon/task_results/<file>.md` | read (collect results) | write (own file only) | read only | read |
| `.archon/proof-journal/` | read | do not access | **write** | read |
| `.archon/PROJECT_STATUS.md` | read | do not access | **write** | read |

## Lean Project
The Lean project is at the repository root. `.archon/` is the coordination layer.
All `.lean` files live in the standard Lean project layout (e.g. `src/`).
The `lake` tool manages dependencies and builds.

## Stages
1. **autoformalize**: Translate informal proofs into Lean skeletons with `sorry` placeholders
2. **prover**: Fill `sorry` placeholders with complete proofs
3. **polish**: Verify, clean, and improve compiled proofs
"""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class Phase3ArchonScaffoldingState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    project_name: str
    statement: str
    stage: Literal[
        "BOOTSTRAP",
        "REFERENCES_INGEST",
        "PROJECT_INIT",
        "AUTO_FORMALIZE",
        "MODULE_SPLIT",
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

    # Phase 2 bridge: informal proof content
    informal_proof_content: str
    candidate_proof_path: str

    # Archon-specific state
    archon_state_root: str
    lean_project_root: str
    references_index_path: str
    module_files: list[str]
    sorry_count: int
    artifact_manifest: dict
    artifacts: Annotated[list[str], merge_artifacts]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _host_project_root(thread_id: str, project_name: str) -> Path:
    return _runtime_root() / "threads" / thread_id / "user-data" / "workspace" / project_name


def _lean_package_name(project_name: str) -> str:
    pieces = [piece for piece in re.split(r"[^A-Za-z0-9]+", project_name) if piece]
    if not pieces:
        return "ArchonProject"
    return "".join(piece[:1].upper() + piece[1:] for piece in pieces)


def _normalize_module_filename(filename: str) -> str:
    candidate = Path(str(filename).replace("\\", "/"))
    if candidate.suffix != ".lean":
        candidate = candidate.with_suffix(".lean")
    return str(candidate)


def _module_name_from_relative_path(relative_path: str) -> str:
    return ".".join(Path(relative_path).with_suffix("").parts)


def _lean_comment(text: str) -> str:
    return text.replace("-/", "- /")


def _fallback_module(statement: str, informal_proof: str) -> dict[str, object]:
    return {
        "modules": [
            {
                "filename": "Main.lean",
                "content": (
                    "import Mathlib\n\n"
                    "/-\n"
                    f"Original statement:\n{_lean_comment(statement)}\n\n"
                    f"Informal proof excerpt:\n{_lean_comment(informal_proof[:1200])}\n"
                    "-/\n\n"
                    "def scaffoldPlaceholder : Prop := True\n\n"
                    "theorem scaffold_placeholder : scaffoldPlaceholder := by\n"
                    "  sorry\n"
                ),
            }
        ],
        "theorem_count": 1,
        "sorry_count": 1,
        "mathlib_deps": ["Mathlib"],
        "summary": "Fallback scaffold generated because autoformalize output was unavailable.",
    }


def _extract_json_object(text: str) -> dict:
    output_text = text.strip()
    if output_text.startswith("```"):
        lines = output_text.splitlines()
        if len(lines) >= 2:
            output_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    output_text = output_text.removeprefix("json").strip()
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        start = output_text.find("{")
        end = output_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(output_text[start : end + 1])
        raise


def _normalize_module_content(content: str, imports: list[str]) -> str:
    normalized = content.strip()
    if not normalized:
        normalized = (
            "def scaffoldPlaceholder : Prop := True\n\n"
            "theorem scaffold_placeholder : scaffoldPlaceholder := by\n"
            "  sorry"
        )

    existing_imports = {
        line.strip()
        for line in normalized.splitlines()
        if line.strip().startswith("import ")
    }
    missing_imports = [
        f"import {module}"
        for module in imports
        if module and f"import {module}" not in existing_imports
    ]
    if missing_imports:
        normalized = "\n".join(missing_imports) + "\n\n" + normalized
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _make_model():
    try:
        from deerflow.models import create_chat_model
    except ImportError:
        from deerflow.models.factory import create_chat_model

    model_name = "deepseek-v4"
    try:
        from deerflow.config import get_app_config
        config = get_app_config()
        if getattr(config, "models", None):
            model_name = config.models[0].name
    except Exception:
        pass
    return create_chat_model(model_name, thinking_enabled=True)


def _extract_last_content(result) -> str:
    if isinstance(result, dict):
        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            return str(getattr(last, "content", last))
    return str(result)


def _run_deerflow_agent(prompt: str, *, system_prompt: str, tools=None, thread_id: str) -> str:
    import uuid
    try:
        from deerflow.agents.factory import create_deerflow_agent
    except ImportError:
        from deerflow.agents import create_deerflow_agent

    agent = create_deerflow_agent(
        model=_make_model(),
        tools=tools or [],
        system_prompt=system_prompt,
    )
    result = agent.invoke(
        {"messages": [HumanMessage(content=prompt)]},
        config={"configurable": {"thread_id": thread_id}},
        context={"thread_id": thread_id, "run_id": str(uuid.uuid4())},
    )
    return _extract_last_content(result)


# ---------------------------------------------------------------------------
# Node: references_ingestion_node
# ---------------------------------------------------------------------------

def references_ingestion_node(state: Phase3ArchonScaffoldingState) -> Phase3ArchonScaffoldingState:
    """Scan and index reference materials from the informal/references directories."""
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)

    # Gather available references
    informal_docs: list[dict[str, str]] = []
    informal_dir = project_root / "informal"
    if informal_dir.exists():
        for f in informal_dir.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".txt", ".json"):
                informal_docs.append(
                    {
                        "path": str(f.relative_to(project_root)),
                        "source_root": "informal",
                        "kind": f.suffix.lstrip("."),
                    }
                )

    refs_dir = project_root / "references"
    if refs_dir.exists():
        for f in refs_dir.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".txt", ".json", ".pdf"):
                informal_docs.append(
                    {
                        "path": str(f.relative_to(project_root)),
                        "source_root": "references",
                        "kind": f.suffix.lstrip("."),
                    }
                )

    refs_index_path = project_root / "references" / "structured" / "phase3_reference_index.json"
    refs_index_path.parent.mkdir(parents=True, exist_ok=True)
    refs_index_path.write_text(
        json.dumps(
            {
                "phase": "phase3_archon_scaffolding",
                "project_name": project_name,
                "items": informal_docs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    # Build a references manifest
    refs_manifest = {
        "phase": "phase3_archon_scaffolding",
        "references_ingested": [item["path"] for item in informal_docs],
        "references_index_path": f"{project_name}/references/structured/phase3_reference_index.json",
        "source_phase": "phase2_rethlas",
        "statement": state.get("statement", ""),
    }
    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    refs_manifest_path = project_root / "manifests" / "phase3_references.json"
    refs_manifest_path.write_text(json.dumps(refs_manifest, ensure_ascii=False, indent=2))

    # Load informal proof content if available
    informal_proof_content = state.get("informal_proof_content", "")
    if not informal_proof_content:
        candidate_path = project_root / "informal" / "proofs" / "candidate_proof.md"
        if candidate_path.exists():
            informal_proof_content = candidate_path.read_text()

    return {
        **state,
        "stage": "REFERENCES_INGEST",
        "informal_proof_content": informal_proof_content,
        "references_index_path": f"{state['references_root']}/structured/phase3_reference_index.json",
        "artifacts": [
            f"{project_name}/manifests/phase3_references.json",
            f"{project_name}/references/structured/phase3_reference_index.json",
        ],
    }


# ---------------------------------------------------------------------------
# Node: project_init_node
# ---------------------------------------------------------------------------

def project_init_node(state: Phase3ArchonScaffoldingState) -> Phase3ArchonScaffoldingState:
    """Initialize the .archon/ coordination directory and Lean project skeleton."""
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)

    archon_dir = project_root / ".archon"
    archon_dir.mkdir(parents=True, exist_ok=True)

    # Write Archon template files
    (archon_dir / "PROGRESS.md").write_text(ARCHON_PROGRESS_TEMPLATE)
    (archon_dir / "task_pending.md").write_text(ARCHON_TASK_PENDING_TEMPLATE)
    (archon_dir / "USER_HINTS.md").write_text(ARCHON_USER_HINTS_TEMPLATE)
    (archon_dir / "CLAUDE.md").write_text(ARCHON_CLAUDE_TEMPLATE)
    (archon_dir / "task_done.md").write_text("")

    # Create task_results directory
    (archon_dir / "task_results").mkdir(parents=True, exist_ok=True)

    # Create proof-journal directory
    (archon_dir / "proof-journal").mkdir(parents=True, exist_ok=True)
    (archon_dir / "proof-journal" / "sessions").mkdir(parents=True, exist_ok=True)

    # Create formal Lean project directory structure
    formal_dir = project_root / "formal"
    formal_dir.mkdir(parents=True, exist_ok=True)
    package_name = _lean_package_name(project_name)

    # Minimal lake project files (lean-toolchain, lakefile.lean, src/)
    # Detect installed Lean version, fall back to v4.16.0
    try:
        result = __import__("subprocess").run(
            ["lean", "--version"], capture_output=True, text=True, timeout=5
        )
        version_match = re.search(r"version\s+(\d+\.\d+\.\d+)", result.stdout)
        lean_version = version_match.group(1) if version_match else "4.16.0"
    except Exception:
        lean_version = "4.16.0"

    (formal_dir / "lean-toolchain").write_text(f"leanprover/lean4:v{lean_version}\n")

    lakefile_content = f"""\
import Lake
open Lake DSL

package «{package_name}» where
  -- add package configuration here

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git"

@[default_target]
lean_lib «{package_name}» where
  srcDir := "src"
"""

    (formal_dir / "lakefile.lean").write_text(lakefile_content)

    (formal_dir / "src").mkdir(parents=True, exist_ok=True)
    (formal_dir / "src" / f"{package_name}.lean").write_text("import Mathlib\n")
    (formal_dir / "README.md").write_text(
        "# Formal Scaffold\n\n"
        f"- Lean package: `{package_name}`\n"
        "- Source root: `formal/src`\n"
        "- Expected compile target: all files parse with only `sorry` placeholders remaining.\n"
    )
    (project_root / "journal" / "phase3_scaffolding.md").write_text(
        "# Phase 3 Scaffolding Journal\n\n"
        "- Lean project initialized.\n"
        "- Awaiting autoformalize module generation.\n"
    )

    lean_project_root = str(formal_dir.relative_to(project_root))
    archon_state_root = str(archon_dir.relative_to(project_root))

    return {
        **state,
        "stage": "PROJECT_INIT",
        "lean_project_root": lean_project_root,
        "archon_state_root": archon_state_root,
        "artifacts": [
            f"{project_name}/.archon/PROGRESS.md",
            f"{project_name}/.archon/task_pending.md",
            f"{project_name}/.archon/USER_HINTS.md",
            f"{project_name}/.archon/CLAUDE.md",
            f"{project_name}/formal/lakefile.lean",
            f"{project_name}/formal/lean-toolchain",
            f"{project_name}/formal/src/{package_name}.lean",
            f"{project_name}/journal/phase3_scaffolding.md",
        ],
    }


# ---------------------------------------------------------------------------
# Node: autoformalize_node
# ---------------------------------------------------------------------------

def autoformalize_node(state: Phase3ArchonScaffoldingState) -> Phase3ArchonScaffoldingState:
    """Run the autoformalize agent: informal proof → Lean theorem/definition skeletons."""
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    statement = state.get("statement", "").strip() or "(missing statement)"
    informal_proof = state.get("informal_proof_content", "").strip() or "(no informal proof available)"

    system_prompt = (
        "You are the Archon autoformalize agent.\n"
        "Your job is to translate an informal mathematical proof into Lean 4 theorem and\n"
        "definition skeletons. Follow these rules precisely:\n\n"
        "1. Identify the main theorem statement and helper lemmas from the informal proof.\n"
        "2. Write Lean 4 declarations (theorem/lemma/def) matching the proof structure.\n"
        "3. Place `sorry` at every proof obligation — do NOT attempt full proofs.\n"
        "4. Prefer existing Mathlib definitions; do not reinvent concepts already in Mathlib.\n"
        "5. Use mathematically meaningful names.\n"
        "6. The resulting code must be valid Lean 4 syntax that `lake build` can parse\n"
        "   (even if it can't close the sorries).\n\n"
        "Output format: a JSON object with keys:\n"
        '  - "modules": an array of module definitions, each with "filename" (e.g. "Main.lean")\n'
        '    and "content" (the complete Lean source for that file)\n'
        '  - "theorem_count": total number of theorem/lemma declarations\n'
        '  - "sorry_count": total number of `sorry` placeholders\n'
        '  - "mathlib_deps": array of Mathlib import paths needed\n'
        '  - "summary": brief description of the module structure\n\n'
        "Return ONLY the JSON object, no other text."
    )

    prompt = (
        f"Problem statement:\n{statement}\n\n"
        f"Informal proof:\n{informal_proof}\n\n"
        "Translate this into Lean 4 skeleton code. Output JSON as specified."
    )

    autoformalize_output = _run_deerflow_agent(
        prompt,
        system_prompt=system_prompt,
        tools=[],
        thread_id=f"{thread_id}-archon-autoformalize",
    )

    parsed: dict = {}
    try:
        parsed = _extract_json_object(autoformalize_output)
    except json.JSONDecodeError:
        parsed = _fallback_module(statement, informal_proof)

    # Write module files to formal/src/
    formal_src = project_root / "formal" / "src"
    formal_src.mkdir(parents=True, exist_ok=True)
    module_files: list[str] = []
    modules = parsed.get("modules", []) or _fallback_module(statement, informal_proof)["modules"]
    mathlib_deps = [str(dep) for dep in parsed.get("mathlib_deps", []) if str(dep).strip()] or ["Mathlib"]

    for module_def in modules:
        filename = _normalize_module_filename(module_def.get("filename", "Generated.lean"))
        content = _normalize_module_content(module_def.get("content", ""), mathlib_deps)
        file_path = formal_src / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        module_files.append(f"formal/src/{filename}")

    sorry_count = parsed.get("sorry_count", 0)

    # Write autoformalize report
    report = {
        "phase": "phase3_archon_scaffolding",
        "stage": "autoformalize",
        "theorem_count": parsed.get("theorem_count", 0),
        "sorry_count": sorry_count,
        "mathlib_deps": mathlib_deps,
        "module_summary": parsed.get("summary", ""),
        "module_files": module_files,
        "statement": statement,
    }
    report_path = project_root / "manifests" / "phase3_autoformalize_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    artifacts = [f"{project_name}/manifests/phase3_autoformalize_report.json"]
    artifacts.extend(f"{project_name}/{mf}" for mf in module_files)

    return {
        **state,
        "stage": "AUTO_FORMALIZE",
        "module_files": module_files,
        "sorry_count": sorry_count,
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# Node: module_split_node
# ---------------------------------------------------------------------------

def module_split_node(state: Phase3ArchonScaffoldingState) -> Phase3ArchonScaffoldingState:
    """Verify module splitting and update task_pending.md with per-file entries."""
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)
    module_files = state.get("module_files", [])
    package_name = _lean_package_name(project_name)

    # Build task_pending.md entries for each module
    lines = ["# Index", "<!-- One line per file. Update line numbers when the file changes. -->", ""]
    for mf in module_files:
        lines.append(f"- [ ] {mf} (autoformalize: skeleton with sorries)")
    lines.append("")
    lines.append("---")

    task_pending_path = project_root / ".archon" / "task_pending.md"
    task_pending_path.write_text("\n".join(lines))

    # Update PROGRESS.md objectives
    objectives = [f"- Formalize {Path(mf).name}" for mf in module_files]
    progress_content = (
        "# Project Progress\n\n"
        "## Current Stage\nautoformalize\n\n"
        "## Stages\n"
        "- [x] autoformalize\n"
        "- [ ] prover\n"
        "- [ ] polish\n\n"
        "## Current Objectives\n"
        + "\n".join(objectives)
        + "\n"
    )
    (project_root / ".archon" / "PROGRESS.md").write_text(progress_content)

    root_module_imports = [
        f"import {_module_name_from_relative_path(Path(mf).relative_to('formal/src').as_posix())}"
        for mf in module_files
    ]
    root_module_content = "\n".join(root_module_imports) + ("\n" if root_module_imports else "")
    (project_root / "formal" / "src" / f"{package_name}.lean").write_text(root_module_content or "import Mathlib\n")

    # Build PROJECT_STATUS.md
    project_status = (
        "# Project Status\n\n"
        "## Summary\n"
        f"Autoformalize stage complete. {len(module_files)} module(s) generated with "
        f"{state.get('sorry_count', 0)} total sorry placeholders.\n\n"
        "## Files\n"
    )
    for mf in module_files:
        project_status += f"- `{mf}`\n"
    (project_root / ".archon" / "PROJECT_STATUS.md").write_text(project_status)

    return {
        **state,
        "stage": "MODULE_SPLIT",
        "artifacts": [
            f"{project_name}/.archon/task_pending.md",
            f"{project_name}/.archon/PROGRESS.md",
            f"{project_name}/.archon/PROJECT_STATUS.md",
            f"{project_name}/formal/src/{package_name}.lean",
        ],
    }


# ---------------------------------------------------------------------------
# Node: manifest_node
# ---------------------------------------------------------------------------

def manifest_node(state: Phase3ArchonScaffoldingState) -> Phase3ArchonScaffoldingState:
    """Generate the final Phase 3 manifest tying everything together."""
    thread_id = state["thread_id"]
    project_name = state["project_name"]
    project_root = _host_project_root(thread_id, project_name)

    module_files = state.get("module_files", [])

    manifest = {
        "phase": "phase3_archon_scaffolding",
        "project_name": project_name,
        "statement": state.get("statement", ""),
        "lean_project_root": state.get("lean_project_root", "formal"),
        "archon_state_root": state.get("archon_state_root", ".archon"),
        "references_index_path": state.get("references_index_path", ""),
        "stages_completed": [
            "references_ingestion",
            "project_initialization",
            "autoformalize",
            "module_split",
        ],
        "module_files": module_files,
        "sorry_count": state.get("sorry_count", 0),
        "next_phase": "phase4_archon_proving",
        "contract": {
            "informal_source": state.get("candidate_proof_path", "informal/proofs/candidate_proof.md"),
            "formal_output": "formal/src/*.lean",
            "state_directory": ".archon/",
        },
        "artifacts": state.get("artifacts", []),
    }

    (project_root / "manifests").mkdir(parents=True, exist_ok=True)
    manifest_path = project_root / "manifests" / "phase3_archon_scaffolding.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    return {
        **state,
        "stage": "MANIFEST_READY",
        "artifact_manifest": manifest,
        "artifacts": [f"{project_name}/manifests/phase3_archon_scaffolding.json"],
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def route_after_manifest(state: Phase3ArchonScaffoldingState) -> str:
    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_phase3_archon_scaffolding_graph():
    graph = StateGraph(Phase3ArchonScaffoldingState)

    graph.add_node("bootstrap_layout", bootstrap_layout)
    graph.add_node("references_ingestion", references_ingestion_node)
    graph.add_node("project_init", project_init_node)
    graph.add_node("autoformalize", autoformalize_node)
    graph.add_node("module_split", module_split_node)
    graph.add_node("manifest", manifest_node)

    graph.set_entry_point("bootstrap_layout")
    graph.add_edge("bootstrap_layout", "references_ingestion")
    graph.add_edge("references_ingestion", "project_init")
    graph.add_edge("project_init", "autoformalize")
    graph.add_edge("autoformalize", "module_split")
    graph.add_edge("module_split", "manifest")
    graph.add_conditional_edges("manifest", route_after_manifest, {END: END})

    return graph.compile(checkpointer=_memory_checkpointer())


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run_phase3_archon_scaffolding_workflow(
    thread_id: str,
    statement: str,
    project_name: str = "project",
    informal_proof_content: str = "",
    candidate_proof_path: str = "",
) -> dict:
    return build_phase3_archon_scaffolding_graph().invoke(
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
            "informal_proof_content": informal_proof_content,
            "candidate_proof_path": candidate_proof_path,
            "archon_state_root": "",
            "lean_project_root": "",
            "references_index_path": "",
            "module_files": [],
            "sorry_count": 0,
            "artifact_manifest": {},
            "artifacts": [],
        },
        {"configurable": {"thread_id": thread_id}},
    )
