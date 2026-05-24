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

    langchain_tools = types.ModuleType("langchain.tools")

    def fake_tool(name=None, **_kwargs):
        def decorator(func):
            func.name = name or func.__name__
            return func
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

    workflow_pkg = types.ModuleType("phase2_testpkg")
    workflow_pkg.__path__ = [str(WORKFLOWS_DIR)]
    sys.modules["phase2_testpkg"] = workflow_pkg

    phase1 = _load_module("phase2_testpkg.phase1_runtime", WORKFLOWS_DIR / "phase1_runtime.py")
    skill_tools = _load_module("phase2_testpkg.rethlas_skill_tools", WORKFLOWS_DIR / "rethlas_skill_tools.py")
    phase2 = _load_module("phase2_testpkg.phase2_rethlas", WORKFLOWS_DIR / "phase2_rethlas.py")
    return phase1, phase2, skill_tools


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
        "problem_id": "problem-1",
        "rethlas_memory_root": "",
        "candidate_proof_path": "",
        "verification_report_path": "",
        "attempts": 0,
        "max_attempts": 3,
        "verdict": "pending",
        "verification_summary": "",
        "repair_hints": [],
        "artifacts": [],
    }


def test_phase2_rethlas_repair_loop_and_memory(tmp_path, monkeypatch):
    phase1, phase2, _skill_tools = _load_phase_modules()
    monkeypatch.setenv("ARCHON_DEERFLOW_RUNTIME_ROOT", str(tmp_path / "runtime"))

    responses = iter(
        [
            "First draft with a gap.",
            json.dumps(
                {
                    "verdict": "wrong",
                    "summary": "The proof skips a key implication.",
                    "repair_hints": ["Add the missing implication explicitly."],
                }
            ),
            "Second draft with the missing implication fixed.",
            json.dumps(
                {
                    "verdict": "correct",
                    "summary": "The repaired proof closes the missing step.",
                    "repair_hints": [],
                }
            ),
        ]
    )

    monkeypatch.setattr(phase2, "_run_deerflow_agent", lambda *args, **kwargs: next(responses))

    state = _base_state("thread-phase2", "demo", "Prove True implies True.")
    state = phase1.bootstrap_layout(state, {"configurable": {"thread_id": state["thread_id"]}})
    state = phase2.initialize_rethlas_memory(state)

    state = phase2.generation_agent_node(state)
    state = phase2.verification_agent_node(state)
    assert state["verdict"] == "wrong"
    assert phase2.route_after_verification(state) == "generation_agent"
    assert state["repair_hints"] == ["Add the missing implication explicitly."]

    state = phase2.generation_agent_node(state)
    state = phase2.verification_agent_node(state)
    final_route = phase2.route_after_verification(state)
    state = phase2.finalize_rethlas_state(state)

    project_root = (
        Path(os.environ["ARCHON_DEERFLOW_RUNTIME_ROOT"])
        / "threads"
        / state["thread_id"]
        / "user-data"
        / "workspace"
        / state["project_name"]
    )
    memory_root = project_root / "memory" / "rethlas" / state["problem_id"]

    assert final_route == phase2.END
    assert state["stage"] == "VERIFIED"
    assert state["verdict"] == "correct"
    assert state["attempts"] == 2
    assert "Second draft" in (project_root / "informal" / "proofs" / "candidate_proof.md").read_text()
    assert "missing implication" in (memory_root / "failed_paths.jsonl").read_text()
    assert "repaired proof" in (memory_root / "verifications.jsonl").read_text()
    assert "Second draft" in (memory_root / "proof_steps.jsonl").read_text()


def test_query_memory_uses_rethlas_memory_root_env(tmp_path, monkeypatch):
    _phase1, _phase2, skill_tools = _load_phase_modules()
    memory_root = tmp_path / "memory"
    memory_root.mkdir(parents=True, exist_ok=True)
    (memory_root / "proof_steps.jsonl").write_text(
        json.dumps({"step": "use induction", "note": "helpful"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RETHLAS_MEMORY_ROOT", str(memory_root))

    payload = json.loads(skill_tools.query_memory("induction"))
    assert payload["match_count"] == 1
    assert payload["results"][0]["file"] == "proof_steps.jsonl"


def test_rethlas_skills_write_problem_memory_channels(tmp_path, monkeypatch):
    _phase1, _phase2, skill_tools = _load_phase_modules()
    memory_root = tmp_path / "memory"
    project_root = tmp_path / "project"
    memory_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RETHLAS_MEMORY_ROOT", str(memory_root))
    monkeypatch.setenv("RETHLAS_PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(skill_tools, "_web_search", lambda *args, **kwargs: [{"snippet": "sample snippet", "url": "https://example.com"}])
    monkeypatch.setattr(
        skill_tools,
        "_search_lean",
        lambda *args, **kwargs: [{"name": "Nat.add_zero", "type": "n + 0 = n", "module": "Mathlib", "source": "mathlib-ripgrep"}],
    )

    json.loads(skill_tools.obtain_immediate_conclusions("A -> A"))
    json.loads(skill_tools.search_mathematical_results("n + 0 = n"))
    json.loads(skill_tools.construct_examples("A -> A"))
    json.loads(skill_tools.construct_counterexamples("all swans are blue"))
    json.loads(skill_tools.propose_decomposition("prove A -> A"))
    json.loads(skill_tools.direct_proving("use implication introduction"))
    json.loads(skill_tools.recursive_proving("stuck on subgoal: prove A"))
    json.loads(skill_tools.identify_key_failures("missing lemma route and blocked subgoal"))
    json.loads(skill_tools.verify_proof("A -> A", "Assume A.\nThus A.\nTherefore A."))

    expected_channels = [
        "conclusions",
        "search_results",
        "examples",
        "counterexamples",
        "decompositions",
        "proof_steps",
        "recursive_results",
        "failures",
        "failed_paths",
        "verifications",
    ]
    for channel in expected_channels:
        channel_path = memory_root / f"{channel}.jsonl"
        assert channel_path.exists()
        assert channel_path.read_text(encoding="utf-8").strip()


def test_web_search_disables_direct_http_fallback_by_default(monkeypatch):
    _phase1, _phase2, skill_tools = _load_phase_modules()
    monkeypatch.delenv("RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK", raising=False)
    monkeypatch.setattr(skill_tools, "_invoke_named_tool", lambda *args, **kwargs: None)

    if "deerflow.community.tavily" in sys.modules:
        del sys.modules["deerflow.community.tavily"]

    results = skill_tools._web_search("test query", 3)
    assert results == []



def test_web_search_no_fallback_returns_empty_without_env(monkeypatch):
    """_web_search returns [] when tool registry & Tavily are absent and
    RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK is not set."""
    _phase1, _phase2, skill_tools = _load_phase_modules()
    monkeypatch.delenv("RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK", raising=False)
    monkeypatch.setattr(skill_tools, "_invoke_named_tool", lambda *a, **kw: None)
    if "deerflow.community.tavily" in sys.modules:
        del sys.modules["deerflow.community.tavily"]
    assert skill_tools._web_search("topology definitions", 5) == []


def test_web_fetch_no_fallback_returns_empty_without_env(monkeypatch):
    """_web_fetch returns "" when tool registry is absent and
    RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK is not set."""
    _phase1, _phase2, skill_tools = _load_phase_modules()
    monkeypatch.delenv("RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK", raising=False)
    monkeypatch.setattr(skill_tools, "_invoke_named_tool", lambda *a, **kw: None)
    assert skill_tools._web_fetch("https://example.com") == ""


def test_lean_tools_mcp_only_disables_external_apis_by_default(monkeypatch):
    """lean_theorem_search should not call removed urllib helpers when
    external API sources are requested."""
    from overlay.backend.mcp.lean_tools import lean_theorem_search

    monkeypatch.setenv("RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK", "0")
    result = json.loads(lean_theorem_search("test-query", project_dir=".", source="leansearch"))
    assert result["query"] == "test-query"
    # only local results should appear, no external hits
    for r in result["results"]:
        assert r.get("source") not in ("leansearch-api", "loogle-api", "matlas-api")
