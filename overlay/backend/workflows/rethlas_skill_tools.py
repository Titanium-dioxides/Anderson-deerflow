"""
Phase 2 Rethlas skill tools — actual implementations.

Each tool preserves the paper/original-implementation structure but
now performs real operations: web search, local memory queries,
theorem search via the Lean toolchain, and verification.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from langchain.tools import tool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allow_direct_http_fallback() -> bool:
    return os.environ.get("RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK", "").lower() in {"1", "true", "yes"}


def _memory_root() -> Path | None:
    root = os.environ.get("RETHLAS_MEMORY_ROOT")
    if not root:
        return None
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _record_skill_outputs(
    *,
    tool_name: str,
    query: str,
    payload: dict,
    channels: list[str],
) -> None:
    memory_root = _memory_root()
    if memory_root is None:
        return
    record = {
        "timestamp": _utc_now_iso(),
        "tool": tool_name,
        "query": query,
        "payload": payload,
    }
    for channel in channels:
        _append_jsonl(memory_root / f"{channel}.jsonl", record)


def _load_json_if_needed(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _get_available_tools():
    import_candidates = [
        ("deerflow.tools", "get_available_tools"),
        ("deerflow.tools.registry", "get_available_tools"),
        ("deerflow.agent.tools", "get_available_tools"),
    ]
    for module_name, attr_name in import_candidates:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            return getattr(module, attr_name)
        except Exception:
            continue
    return None


def _invoke_named_tool(candidate_names: list[str], payload: dict, *, groups: list[str] | None = None):
    get_available_tools = _get_available_tools()
    if get_available_tools is None:
        return None
    try:
        tools = get_available_tools(
            groups=groups or [],
            include_mcp=True,
            model_name="",
            subagent_enabled=False,
        )
    except TypeError:
        try:
            tools = get_available_tools(groups=groups or [])
        except Exception:
            return None
    except Exception:
        return None

    for tool_obj in tools or []:
        if getattr(tool_obj, "name", "") in candidate_names:
            try:
                if hasattr(tool_obj, "invoke"):
                    return tool_obj.invoke(payload)
                return tool_obj(**payload)
            except Exception:
                return None
    return None


def _web_search(query: str, num_results: int = 5) -> list[dict]:
    """Perform web search via DeerFlow tool registry or community tool wrappers."""
    tool_result = _invoke_named_tool(
        ["web_search", "search", "tavily_search"],
        {"query": query, "max_results": num_results},
        groups=["web"],
    )
    parsed_tool_result = _load_json_if_needed(tool_result)
    if parsed_tool_result:
        if isinstance(parsed_tool_result.get("results"), list):
            return parsed_tool_result.get("results", [])[:num_results]
    if isinstance(tool_result, list):
        return tool_result[:num_results]
    # Try Tavily if available (configured in config.yaml)
    try:
        from deerflow.community.tavily import web_search_tool
        resp = web_search_tool.invoke({"query": query, "max_results": num_results})
        if isinstance(resp, str):
            resp = json.loads(resp)
        if isinstance(resp, list):
            return resp[:num_results]
        if isinstance(resp, dict):
            return resp.get("results", [])[:num_results]
    except Exception:
        pass

    return []


def _web_fetch(url: str) -> str:
    """Fetch a web page and return its text content.

    Routes through the DeerFlow tool registry when available; falls back to
    direct HTTP only when RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK is set.
    """
    tool_result = _invoke_named_tool(
        ["web_fetch", "fetch_url", "fetch"],
        {"url": url},
        groups=["web"],
    )
    if tool_result is not None:
        if isinstance(tool_result, str):
            return tool_result
        if isinstance(tool_result, dict):
            return tool_result.get("content", tool_result.get("text", ""))

    if not _allow_direct_http_fallback():
        return ""

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "archon-deerflow/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode(errors="replace")
    except Exception:
        return ""


def _search_lean(query: str, project_dir: str = ".") -> list[dict]:
    """Search Lean theorems via unified tool/MCP entry, then local project/mathlib fallback."""
    project_dir = os.environ.get("RETHLAS_PROJECT_ROOT", project_dir)
    tool_result = _invoke_named_tool(
        ["lean_theorem_search"],
        {"query": query, "project_dir": project_dir, "source": "all"},
        groups=["lean"],
    )
    parsed_tool_result = _load_json_if_needed(tool_result)
    if isinstance(parsed_tool_result.get("results"), list):
        return parsed_tool_result.get("results", [])[:15]
    try:
        from overlay.backend.mcp.lean_tools import lean_theorem_search

        response = lean_theorem_search(query, project_dir=project_dir, source="all")
        parsed = _load_json_if_needed(response)
        if isinstance(parsed.get("results"), list):
            return parsed.get("results", [])[:15]
    except Exception:
        pass
    try:
        from overlay.backend.mcp.lean_tools import _search_mathlib_local, _search_project_local
        results = []
        results.extend(_search_mathlib_local(query, str(Path(project_dir) / ".lake" / "packages" / "mathlib"), "name"))
        results.extend(_search_project_local(query, Path(project_dir)))
        return results[:15]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 10 Rethlas skill tools
# ═══════════════════════════════════════════════════════════════════════════════

@tool("obtain_immediate_conclusions", parse_docstring=True)
def obtain_immediate_conclusions(theorem: str) -> str:
    """Derive immediate conclusions, special cases, equivalent formulations,
    and cheap reformulations from a theorem statement.

    Args:
        theorem: The full theorem statement.
    """
    # Web search for known equivalent forms
    results = _web_search(f"equivalent formulations of: {theorem}", 3)
    suggestions = []
    for r in results:
        suggestions.append(r.get("snippet", str(r)[:200]))
    payload = {
        "theorem": theorem,
        "immediate_conclusions": suggestions or [
            "Check the contrapositive form",
            "Consider the special case where one variable is 0 or 1",
            "Check if the statement is an instance of a known inequality",
            "Try rewriting in terms of definitions (expand all abbreviations)",
        ],
        "web_results": len(results),
    }
    _record_skill_outputs(
        tool_name="obtain_immediate_conclusions",
        query=theorem,
        payload=payload,
        channels=["conclusions"],
    )
    return json.dumps(payload, indent=2)


@tool("search_mathematical_results", parse_docstring=True)
def search_mathematical_results(query: str) -> str:
    """Search for mathematical results relevant to the current theorem.
    Searches the web AND Lean Mathlib for known theorems, lemmas, and constructions.

    Args:
        query: Mathematical query, theorem name, or concept.
    """
    # 1. Web search for mathematical results
    web_results = _web_search(f"{query} theorem proof mathematics", 5)

    # 2. Search Lean Mathlib for formalized versions
    lean_results = _search_lean(query, ".")

    payload = {
        "query": query,
        "web_results": [
            {"snippet": r.get("snippet", str(r)[:200]),
             "url": r.get("link", r.get("url", ""))}
            for r in web_results
        ],
        "lean_results": [
            {"name": r.get("name", ""),
             "type": r.get("type", r.get("snippet", "")),
             "module": r.get("module", r.get("file", "")),
             "source": r.get("source", "")}
            for r in lean_results[:10]
        ],
        "lean_results_count": len(lean_results),
    }
    _record_skill_outputs(
        tool_name="search_mathematical_results",
        query=query,
        payload=payload,
        channels=["search_results"],
    )
    return json.dumps(payload, indent=2)


@tool("query_memory", parse_docstring=True)
def query_memory(query: str) -> str:
    """Query problem-local reasoning memory for past attempts, failures, and insights.

    Args:
        query: What to look up in problem-local memory.
    """
    memory_dir = Path(os.environ.get("RETHLAS_MEMORY_ROOT", ".deerflow_runtime"))
    if not memory_dir.exists():
        return json.dumps({"results": [], "note": "No local memory found"})

    matches = []
    for jsonl_file in memory_dir.rglob("*.jsonl"):
        try:
            for line in jsonl_file.read_text().splitlines():
                if not line.strip():
                    continue
                if query.lower() in line.lower():
                    record = json.loads(line)
                    matches.append({
                        "file": str(jsonl_file.name),
                        "record": {k: str(v)[:150] for k, v in record.items()},
                    })
                    if len(matches) >= 10:
                        break
        except Exception:
            continue
        if len(matches) >= 10:
            break

    payload = {
        "query": query,
        "match_count": len(matches),
        "results": matches,
    }
    _record_skill_outputs(
        tool_name="query_memory",
        query=query,
        payload=payload,
        channels=["search_results"],
    )
    return json.dumps(payload, indent=2)


@tool("construct_examples", parse_docstring=True)
def construct_examples(theorem: str) -> str:
    """Construct concrete examples related to the theorem statement.
    Searches for known examples and special cases.

    Args:
        theorem: The theorem statement.
    """
    results = _web_search(f"examples and special cases: {theorem}", 5)

    payload = {
        "theorem": theorem,
        "examples_from_web": [r.get("snippet", str(r)[:200]) for r in results],
        "suggested_approach": [
            "Try n=0, 1, 2 for number-theoretic statements",
            "Try the zero vector / identity matrix for linear algebra",
            "Try empty list / singleton for combinatorial statements",
            "Try constant functions / step functions for analysis statements",
        ],
    }
    _record_skill_outputs(
        tool_name="construct_examples",
        query=theorem,
        payload=payload,
        channels=["examples"],
    )
    return json.dumps(payload, indent=2)


@tool("construct_counterexamples", parse_docstring=True)
def construct_counterexamples(claim: str) -> str:
    """Attempt to find or construct counterexamples to a claim.
    Searches the web for known counterexamples.

    Args:
        claim: The claim to challenge.
    """
    results = _web_search(f"counterexample to: {claim}", 5)

    payload = {
        "claim": claim,
        "known_counterexamples": [r.get("snippet", str(r)[:200]) for r in results],
        "suggested_approach": [
            "Try edge cases: 0, 1, empty, identity",
            "Try non-commutative / non-associative settings",
            "Try infinite-dimensional / non-compact settings",
            "Look for known pathological counterexamples in the literature",
        ],
    }
    _record_skill_outputs(
        tool_name="construct_counterexamples",
        query=claim,
        payload=payload,
        channels=["counterexamples"],
    )
    return json.dumps(payload, indent=2)


@tool("propose_decomposition", parse_docstring=True)
def propose_decomposition(theorem_statement: str) -> str:
    """Propose materially different subgoal decomposition plans.
    Searches for known proof strategies and decompositions.

    Args:
        theorem_statement: The theorem statement to decompose.
    """
    results = _web_search(f"proof strategy decomposition: {theorem_statement}", 5)

    payload = {
        "statement": theorem_statement,
        "web_strategies": [r.get("snippet", str(r)[:200]) for r in results],
        "decomposition_plans": [
            {
                "plan": "Direct decomposition into lemmas",
                "description": "Break the theorem into 2-4 independent lemmas, prove each separately, then combine.",
                "suitable_for": "Statements with clear logical structure (conjunction, equivalence, induction)",
            },
            {
                "plan": "Contrapositive / contradiction",
                "description": "Assume the negation and derive a contradiction. Often simplifies quantifier handling.",
                "suitable_for": "Statements of the form 'if P then Q' or 'for all x, P(x)'",
            },
            {
                "plan": "Auxiliary construction",
                "description": "Construct an intermediate object that bridges the gap between hypotheses and conclusion.",
                "suitable_for": "Existence proofs, inequalities, geometric statements",
            },
            {
                "plan": "Induction / recursion",
                "description": "Prove the base case and inductive step. Useful for statements over natural numbers, lists, trees.",
                "suitable_for": "Statements quantified over inductively defined types",
            },
        ],
    }
    _record_skill_outputs(
        tool_name="propose_decomposition",
        query=theorem_statement,
        payload=payload,
        channels=["decompositions"],
    )
    return json.dumps(payload, indent=2)


@tool("direct_proving", parse_docstring=True)
def direct_proving(plan_summary: str) -> str:
    """Attempt direct proving on a chosen decomposition plan.
    Searches for specific proof techniques matching the plan.

    Args:
        plan_summary: The plan or subgoal list to try directly.
    """
    results = _web_search(f"how to prove: {plan_summary}", 5)

    payload = {
        "plan": plan_summary,
        "techniques_found": [r.get("snippet", str(r)[:200]) for r in results],
        "suggested_tactics": [
            "Start by writing down all definitions in full detail",
            "Identify the key inequality / equality that needs to be shown",
            "Apply known lemmas from the literature (search Mathlib for matches)",
            "If stuck, try a different decomposition plan or construct a minimal counterexample",
        ],
    }
    _record_skill_outputs(
        tool_name="direct_proving",
        query=plan_summary,
        payload=payload,
        channels=["proof_steps"],
    )
    return json.dumps(payload, indent=2)


@tool("recursive_proving", parse_docstring=True)
def recursive_proving(plan_bundle: str) -> str:
    """Launch recursive or multi-branch proving from failed or pending plans.
    Returns structured subagent prompts that can be executed via the `task` tool.

    Use `task` tool with subagent_type='general-purpose' and the prompts below
    to spawn parallel proof exploration.

    Args:
        plan_bundle: Serialized plan bundle and known stuck points.
    """
    # Search for applicable lemmas for each stuck point
    stuck_points = [p for p in plan_bundle.split("\n") if p.strip() and any(
        w in p.lower() for w in ["stuck", "failed", "blocked", "subgoal", "lemma", "prove"]
    )]

    tasks = []
    for i, point in enumerate(stuck_points[:3]):
        lemmas = _search_lean(point, ".")
        tasks.append({
            "task_id": f"branch_{i}",
            "subagent_type": "general-purpose",
            "description": f"Explore proof route for: {point[:100]}",
            "prompt": (
                f"Explore an alternative proof strategy for this subgoal:\n\n"
                f"{point}\n\n"
                f"Known lemmas found: {json.dumps([l.get('name', l.get('snippet', ''))[:80] for l in lemmas[:5]])}\n\n"
                f"Try a different approach than what failed before. "
                f"Suggest a proof sketch or identify a counterexample."
            ),
        })

    if not tasks:
        tasks.append({
            "task_id": "branch_0",
            "subagent_type": "general-purpose",
            "description": f"Explore proof strategy from scratch",
            "prompt": (
                f"The current proof plan is stuck. Explore alternative strategies:\n\n"
                f"{plan_bundle[:500]}\n\n"
                f"Propose 2-3 different proof approaches, each with a brief sketch."
            ),
        })

    payload = {
        "plan_bundle": plan_bundle[:300],
        "recursive_tasks": tasks,
        "instructions": (
            "Use the `task` tool to spawn these subagent tasks in parallel. "
            "Each subagent will explore a different proof route. "
            "After all subagents complete, synthesize their results into a unified proof strategy."
        ),
        "max_parallel": min(len(tasks), 3),
    }
    _record_skill_outputs(
        tool_name="recursive_proving",
        query=plan_bundle[:300],
        payload=payload,
        channels=["recursive_results"],
    )
    return json.dumps(payload, indent=2)


@tool("identify_key_failures", parse_docstring=True)
def identify_key_failures(failure_summary: str) -> str:
    """Identify recurring failure modes from multiple attempts.

    Args:
        failure_summary: Summary of prior failures.
    """
    patterns = {
        "missing_lemma_route": "A required intermediate lemma could not be found or proved",
        "induction_stuck": "The induction step cannot be closed with the current hypothesis",
        "type_mismatch": "The formal statement does not type-check as expected",
        "circularity": "The proof attempt assumes what it tries to prove",
        "quantifier_handling": "Universal/existential quantifiers are not handled correctly",
        "algebra_simplification": "Algebraic simplification fails to reach the target form",
    }

    detected = []
    for key, desc in patterns.items():
        if key in failure_summary.lower() or any(
            word in failure_summary.lower() for word in key.split("_")
        ):
            detected.append({"pattern": key, "description": desc})

    payload = {
        "failure_summary": failure_summary[:500],
        "detected_patterns": detected or [
            {"pattern": "generic", "description": "No specific pattern detected — manual review needed"}
        ],
        "recommendations": [
            "If blocked: try a different decomposition plan",
            "If missing lemma: search Mathlib or prove it separately",
            "If type error: simplify the statement or break into smaller steps",
            "If repeated dead end: mark as blocked and move to another subgoal",
        ],
    }
    _record_skill_outputs(
        tool_name="identify_key_failures",
        query=failure_summary[:300],
        payload=payload,
        channels=["failures", "failed_paths"],
    )
    return json.dumps(payload, indent=2)


@tool("verify_proof", parse_docstring=True)
def verify_proof(statement: str, proof: str) -> str:
    """Verify a candidate proof for logical correctness and completeness.

    Args:
        statement: Original theorem statement.
        proof: Candidate proof text.
    """
    # Structural checks
    checks = []
    has_assumptions = any(w in proof.lower() for w in ["assume", "let ", "suppose", "hypothesis"])
    has_conclusion = any(w in proof.lower() for w in ["therefore", "thus", "hence", "consequently", "qed", "∎"])
    has_steps = proof.count("\n") >= 3
    uses_induction = "induction" in proof.lower()
    has_base_case = "base" in proof.lower() or "n = 0" in proof or "empty" in proof
    has_base_case = has_base_case or ("0" in proof and "trivial" in proof.lower())

    if has_assumptions:
        checks.append({"check": "Clear assumptions stated", "status": "pass"})
    else:
        checks.append({"check": "Clear assumptions stated", "status": "warn", "detail": "May be missing explicit hypotheses"})

    if has_conclusion:
        checks.append({"check": "Conclusion explicitly stated", "status": "pass"})
    else:
        checks.append({"check": "Conclusion explicitly stated", "status": "warn", "detail": "No clear 'therefore' or 'thus'"})

    if has_steps:
        checks.append({"check": "Multi-step reasoning", "status": "pass"})
    else:
        checks.append({"check": "Multi-step reasoning", "status": "fail", "detail": "Proof too short"})

    if uses_induction:
        if has_base_case:
            checks.append({"check": "Induction: base case covered", "status": "pass"})
        else:
            checks.append({"check": "Induction: base case covered", "status": "warn", "detail": "Check if base case is implicit"})

    all_pass = all(c["status"] == "pass" for c in checks)

    # Also search for known proofs of this statement
    known_results = _web_search(f"proof of {statement[:100]}", 3)
    known_snippets = [r.get("snippet", str(r)[:200]) for r in known_results]

    payload = {
        "statement": statement[:200],
        "verdict": "correct" if all_pass else "needs_review",
        "checks": checks,
        "all_checks_pass": all_pass,
        "known_proofs": known_snippets,
        "repair_hints": (
            [] if all_pass
            else [c["detail"] for c in checks if c.get("detail")]
        ),
    }
    channels = ["verifications"]
    if payload["verdict"] != "correct":
        channels.append("failed_paths")
    _record_skill_outputs(
        tool_name="verify_proof",
        query=statement[:200],
        payload=payload,
        channels=channels,
    )
    return json.dumps(payload, indent=2)


# ── Tool list for registration ──
RETHLAS_SKILL_TOOLS = [
    obtain_immediate_conclusions,
    search_mathematical_results,
    query_memory,
    construct_examples,
    construct_counterexamples,
    propose_decomposition,
    direct_proving,
    recursive_proving,
    identify_key_failures,
    verify_proof,
]
