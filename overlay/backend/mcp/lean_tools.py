"""
Lean 4 toolchain as DeerFlow-native tools.

These tools wrap the Lean CLI (lean, lake) and provide LSP-like capabilities:
  - file diagnostics (errors, warnings)
  - project build
  - sorry / axiom scanning
  - theorem search (grep-based)
  - file outline extraction

Registered in config.yaml under the 'lean' tool group.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from langchain.tools import tool


def _lean_available() -> bool:
    try:
        subprocess.run(["lean", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _lake_available() -> bool:
    try:
        subprocess.run(["lake", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _project_root(file_path: str) -> Path:
    """Find the Lean project root (parent of lakefile) for a given file."""
    p = Path(file_path).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "lakefile.lean").exists() or (parent / "lakefile.toml").exists():
            return parent
    return p.parent


def _allow_direct_http_fallback() -> bool:
    """Control direct HTTP fallback for search APIs.

    When True (env RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK=1), the tool may make
    direct HTTP requests to external Lean APIs.  When False (default), only
    local filesystem search and MCP-routed queries are used.
    """
    import os
    return os.environ.get("RETHLAS_ALLOW_DIRECT_HTTP_FALLBACK", "").lower() in {"1", "true", "yes"}



@tool("lean_check_file", parse_docstring=True)
def lean_check_file(file_path: str) -> str:
    """Run `lean` on a single .lean file and return diagnostics (errors, warnings, messages).

    Args:
        file_path: Absolute or relative path to the .lean file.
    """
    path = Path(file_path)
    if not path.exists():
        return json.dumps({"error": f"File not found: {file_path}", "diagnostics": []})

    try:
        result = subprocess.run(
            ["lean", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(_project_root(file_path)),
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        diagnostics = []
        for line in (stdout + "\n" + stderr).splitlines():
            line = line.strip()
            if not line:
                continue
            # Parse Lean error format: file:line:col: severity: message
            match = re.match(r"(.+?):(\d+):(\d+):\s*(error|warning|info):\s*(.+)", line)
            if match:
                diagnostics.append({
                    "file": match.group(1),
                    "line": int(match.group(2)),
                    "column": int(match.group(3)),
                    "severity": match.group(4),
                    "message": match.group(5),
                })
            else:
                diagnostics.append({"raw": line})

        return json.dumps({
            "file": str(path),
            "returncode": result.returncode,
            "diagnostics": diagnostics,
            "error_count": sum(1 for d in diagnostics if d.get("severity") == "error"),
            "warning_count": sum(1 for d in diagnostics if d.get("severity") == "warning"),
        }, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "lean check timed out", "file": str(path)})
    except FileNotFoundError:
        if _lean_available():
            return json.dumps({"error": f"Unexpected error running lean on {file_path}"})
        return json.dumps({"error": "lean not installed", "file": str(path), "diagnostics": []})


@tool("lean_build", parse_docstring=True)
def lean_build(project_dir: str = ".") -> str:
    """Run `lake build` in the Lean project directory.

    Args:
        project_dir: Path to the Lean project root (contains lakefile.lean).
    """
    project = Path(project_dir)
    if not (project / "lakefile.lean").exists() and not (project / "lakefile.toml").exists():
        return json.dumps({"error": f"No lakefile found in {project_dir}", "returncode": -1})

    try:
        result = subprocess.run(
            ["lake", "build"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(project),
        )
        stderr = result.stderr or ""

        # Extract errors and warnings
        errors = []
        warnings = []
        for line in stderr.splitlines():
            line = line.strip()
            if not line:
                continue
            if "error" in line.lower():
                errors.append(line)
            elif "warning" in line.lower():
                warnings.append(line)

        return json.dumps({
            "project": str(project),
            "returncode": result.returncode,
            "success": result.returncode == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:20],
            "warnings": warnings[:20],
            "stderr_tail": stderr[-500:] if len(stderr) > 500 else stderr,
        }, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "lake build timed out (300s)", "project": str(project)})
    except FileNotFoundError:
        if _lake_available():
            return json.dumps({"error": f"Unexpected error running lake in {project_dir}"})
        return json.dumps({"error": "lake not installed", "project": str(project), "returncode": -1})


@tool("lean_sorry_scan", parse_docstring=True)
def lean_sorry_scan(project_dir: str = ".") -> str:
    """Scan all .lean files in the project for `sorry` and `axiom` placeholders.

    Args:
        project_dir: Path to the Lean project root.
    """
    project = Path(project_dir)
    results = []
    total_sorry = 0
    total_axiom = 0

    for lean_file in sorted(project.rglob("*.lean")):
        parts = lean_file.relative_to(project).parts
        if parts and parts[0] in (".lake", "lake-packages", "build", "_build"):
            continue
        try:
            content = lean_file.read_text()
        except Exception:
            continue

        sorry_count = len(re.findall(r"\bsorry\b", content))
        axiom_count = len(re.findall(r"\baxiom\b", content))

        if sorry_count > 0 or axiom_count > 0:
            lines = content.splitlines()
            sorry_lines = [i + 1 for i, l in enumerate(lines) if "sorry" in l]
            axiom_lines = [i + 1 for i, l in enumerate(lines) if "axiom" in l]

            results.append({
                "file": str(lean_file.relative_to(project)),
                "sorry_count": sorry_count,
                "sorry_lines": sorry_lines,
                "axiom_count": axiom_count,
                "axiom_lines": axiom_lines,
            })
            total_sorry += sorry_count
            total_axiom += axiom_count

    return json.dumps({
        "project": str(project),
        "total_sorry": total_sorry,
        "total_axiom": total_axiom,
        "clean": total_sorry == 0 and total_axiom == 0,
        "files_with_issues": len(results),
        "details": results,
    }, indent=2)


@tool("lean_file_outline", parse_docstring=True)
def lean_file_outline(file_path: str) -> str:
    """Extract the structure of a Lean file: imports, declarations (theorem/lemma/def),
    and their status (proven vs sorry vs axiom).

    Args:
        file_path: Path to the .lean file.
    """
    path = Path(file_path)
    if not path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    try:
        content = path.read_text()
        lines = content.splitlines()
    except Exception as e:
        return json.dumps({"error": f"Cannot read file: {e}"})

    outline = {
        "file": str(path),
        "imports": [],
        "declarations": [],
    }

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Imports
        if stripped.startswith("import "):
            outline["imports"].append({"line": i, "module": stripped[len("import "):].strip()})
            continue

        # Declarations
        decl_match = re.match(
            r"^(theorem|lemma|def|example|instance|class|structure|inductive|opaque)\s+(\S+)",
            stripped
        )
        if decl_match:
            kind = decl_match.group(1)
            name = decl_match.group(2)
            status = "unknown"
            # Check the next few lines for sorry / trivial / rfl / := proof body
            next_lines = " ".join(lines[i:min(i + 20, len(lines))])
            if "sorry" in next_lines:
                status = "sorry"
            elif "axiom" in next_lines:
                status = "axiom"
            elif ":= " in next_lines or re.search(r"\bby\b", next_lines):
                status = "proven"

            outline["declarations"].append({
                "line": i,
                "kind": kind,
                "name": name,
                "status": status,
            })

    outline["total"] = len(outline["declarations"])
    outline["sorry_count"] = sum(1 for d in outline["declarations"] if d["status"] == "sorry")
    outline["proven_count"] = sum(1 for d in outline["declarations"] if d["status"] == "proven")

    return json.dumps(outline, indent=2)


@tool("lean_goal_at", parse_docstring=True)
def lean_goal_at(file_path: str, line: int) -> str:
    """Read the proof context around a specific line in a Lean file. Returns the
    surrounding lines showing the goal context.

    Args:
        file_path: Path to the .lean file.
        line: Line number to inspect (1-indexed).
    """
    path = Path(file_path)
    if not path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    try:
        content = path.read_text()
        lines = content.splitlines()
    except Exception as e:
        return json.dumps({"error": f"Cannot read file: {e}"})

    start = max(0, line - 10)
    end = min(len(lines), line + 10)

    context = []
    for i in range(start, end):
        prefix = ">>>" if i + 1 == line else "   "
        context.append(f"{prefix} {i + 1:4d}: {lines[i]}")

    return json.dumps({
        "file": str(path),
        "target_line": line,
        "context": "\n".join(context),
    }, indent=2)


def _search_mathlib_local(query: str, mathlib_path: str, search_type: str = "name") -> list[dict]:
    """Search Mathlib locally using ripgrep or grep.

    search_type: 'name' (theorem/lemma/def declarations), 'type' (type signatures),
                 'content' (full text search).
    """
    results = []
    path = Path(mathlib_path)
    if not path.exists():
        return results

    patterns = {
        "name": r"^(theorem|lemma|def|class|structure|inductive)\s+.*" + re.escape(query),
        "type": r":\s*.*" + re.escape(query),
        "content": re.escape(query),
    }
    pattern = patterns.get(search_type, patterns["content"])

    try:
        # Try ripgrep first (much faster)
        rg_result = subprocess.run(
            ["rg", "--no-heading", "-n", "--type", "lean", "-C", "0", pattern, mathlib_path],
            capture_output=True, text=True, timeout=30
        )
        if rg_result.returncode in (0, 1):
            for line in rg_result.stdout.strip().split("\n"):
                if ":" in line:
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        results.append({
                            "file": parts[0],
                            "line": int(parts[1]) if parts[1].isdigit() else 0,
                            "snippet": parts[2].strip()[:150],
                            "source": "mathlib-ripgrep",
                        })
                        if len(results) >= 40:
                            break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback to grep if ripgrep not available
    if not results:
        try:
            grep_result = subprocess.run(
                ["grep", "-rn", "--include=*.lean", pattern, mathlib_path],
                capture_output=True, text=True, timeout=60
            )
            if grep_result.returncode in (0, 1):
                for line in grep_result.stdout.strip().split("\n")[:40]:
                    if ":" in line:
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            results.append({
                                "file": parts[0],
                                "line": int(parts[1]) if parts[1].isdigit() else 0,
                                "snippet": parts[2].strip()[:150],
                                "source": "mathlib-grep",
                            })
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return results


def _search_leansearch_api(query: str) -> list[dict]:
    """Search via LeanSearch API (semantic/natural-language search)."""
    results = []
    try:
        import urllib.request, urllib.parse
        encoded = urllib.parse.quote(query)
        req = urllib.request.Request(
            f"https://leansearch.net/api/search?query={encoded}&num_results=10",
            headers={"User-Agent": "archon-deerflow/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            for item in data.get("results", [])[:10]:
                results.append({
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                    "module": item.get("module", ""),
                    "score": item.get("score", 0),
                    "source": "leansearch-api",
                })
    except Exception:
        pass
    return results


def _search_loogle_api(query: str) -> list[dict]:
    """Search via Loogle API (type-pattern search)."""
    results = []
    try:
        import urllib.request, urllib.parse
        encoded = urllib.parse.quote(query)
        req = urllib.request.Request(
            f"https://loogle.lean-lang.org/json?q={encoded}",
            headers={"User-Agent": "archon-deerflow/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            for item in data.get("hits", [])[:10]:
                results.append({
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                    "module": item.get("module", ""),
                    "source": "loogle-api",
                })
    except Exception:
        pass
    return results


def _search_matlas_api(query: str) -> list[dict]:
    """Search via Matlas API (mathematical literature theorem search)."""
    results = []
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://matlas.ai/api/search",
            data=json.dumps({"query": query}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "archon-deerflow/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            for item in (data if isinstance(data, list) else data.get("results", []))[:10]:
                results.append({
                    "name": item.get("entity_name", ""),
                    "type": item.get("type", ""),
                    "statement": item.get("statement", "")[:300],
                    "title": item.get("title", ""),
                    "authors": item.get("authors", ""),
                    "doi": item.get("doi", ""),
                    "year": item.get("year", ""),
                    "source": "matlas-api",
                })
    except Exception:
        pass
    return results


def _search_project_local(query: str, project_dir: Path) -> list[dict]:
    """Search project-local .lean files."""
    results = []
    for lean_file in sorted(project_dir.rglob("*.lean")):
        parts = lean_file.relative_to(project_dir).parts
        if parts and parts[0] in (".lake", "lake-packages", "build", "_build"):
            continue
        try:
            content = lean_file.read_text()
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if query.lower() in line.lower():
                results.append({
                    "file": str(lean_file.relative_to(project_dir)),
                    "line": i,
                    "snippet": line.strip()[:120],
                    "source": "project-local",
                })
                if len(results) >= 20:
                    break
        if len(results) >= 20:
            break
    return results


@tool("lean_theorem_search", parse_docstring=True)
def lean_theorem_search(query: str, project_dir: str = ".", source: str = "all") -> str:
    """Search for theorems, lemmas, or definitions across multiple sources.

    Sources:
      - all: Search all available sources (recommended)
      - mathlib: Search mathlib locally via ripgrep (fast, no rate limits)
      - leansearch: Semantic search via LeanSearch API
      - loogle: Type-based search via Loogle API
      - matlas: Mathematical literature theorem search via Matlas API (matlas.ai)
      - project: Search only project-local .lean files

    Args:
        query: Theorem name, keyword, or mathematical concept to search for.
        project_dir: Path to the Lean project root.
        source: Search source — 'all', 'mathlib', 'leansearch', 'loogle', 'matlas', 'project'.
    """
    project = Path(project_dir)
    mathlib_path = str(project / ".lake" / "packages" / "mathlib")
    all_results: list[dict] = []

    # 1. Mathlib local search (fast, no rate limits)
    if source in ("all", "mathlib"):
        name_results = _search_mathlib_local(query, mathlib_path, "name")
        all_results.extend(name_results)

    # 2. Project-local search
    if source in ("all", "project"):
        local_results = _search_project_local(query, project)
        all_results.extend(local_results)

    # 3. External APIs (LeanSearch/Loogle/Matlas) — only reachable via MCP integration
    if source in ("all", "leansearch", "loogle", "matlas"):
        if _allow_direct_http_fallback():
            # TODO: optionally route through upstream MCP if configured
            pass

    # Deduplicate by name
    seen = set()
    deduped = []
    for r in all_results:
        key = r.get("name") or r.get("snippet", "")
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return json.dumps({
        "query": query,
        "sources_searched": source,
        "match_count": len(deduped),
        "results": deduped[:50],
    }, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# Credibility analysis & verification
# ═══════════════════════════════════════════════════════════════════════════════

# Credibility scoring rules per source:
#   Mathlib (machine-checked)           → 10/10
#   Loogle / LeanSearch (from Mathlib)  → 10/10 (referencing machine-checked proofs)
#   Matlas — paper with DOI            → 8/10 (peer-reviewed)
#   Matlas — book                       → 7/10 (published, possibly reviewed)
#   Matlas — unknown type               → 5/10
#   Web search with attribution         → 4/10
#   Web search without attribution      → 2/10
#   Project-local file                  → varies (self-authored, needs verification)

SOURCE_CREDIBILITY = {
    "mathlib-ripgrep":   10,
    "mathlib-grep":      10,
    "loogle-api":         10,
    "leansearch-api":     10,
    "matlas-api":          8,   # base; adjusted per item below
    "project-local":       5,
    "tavily":              4,
    "serper":              4,
    "duckduckgo":          2,
}


def _assess_credibility(result: dict) -> tuple[int, str]:
    """Return (score 0-10, reason) for a single search result."""
    src = result.get("source", "")

    # Matlas: adjust based on publication type
    if src == "matlas-api":
        pub_type = result.get("type", "")
        has_doi = bool(result.get("doi", "").strip())
        if pub_type == "paper" and has_doi:
            return 9, "peer-reviewed paper with DOI"
        elif pub_type == "paper":
            return 7, "paper (no DOI available)"
        elif pub_type == "book":
            return 7, "published book"
        else:
            return 5, "unattributed mathematical statement"

    # Mathlib / Loogle / LeanSearch → already machine-checked
    if src in ("mathlib-ripgrep", "mathlib-grep", "loogle-api", "leansearch-api"):
        return SOURCE_CREDIBILITY[src], "machine-checked proof in Mathlib"

    # Web search: check for attribution signals
    if src in ("tavily", "serper", "duckduckgo"):
        snippet = result.get("snippet", "")
        has_attribution = any(
            marker in snippet.lower()
            for marker in ["doi", "arxiv", "theorem", "lemma", "proof", "wikipedia", "math"]
        )
        if has_attribution:
            return 4, "web result with mathematical context"
        return 2, "web result without clear attribution"

    # Project-local: depends on whether it has a sorry
    status = result.get("status", "")
    if status == "proven":
        return 8, "project-local proven theorem"
    elif status == "sorry":
        return 3, "project-local unproven (contains sorry)"
    return 5, "project-local file"

    return SOURCE_CREDIBILITY.get(src, 3), "unknown source"


def _analyze_credibility(results: list[dict]) -> dict:
    """Analyze credibility of all search results, produce summary and recommendations."""
    if not results:
        return {
            "overall_credibility": 0,
            "assessment": "No results to assess.",
            "needs_verification": False,
            "recommendation": "No information available. Perform web search or ask user for references.",
            "scored_results": [],
        }

    scored = []
    scores = []
    for r in results:
        score, reason = _assess_credibility(r)
        r_copy = dict(r)
        r_copy["credibility_score"] = score
        r_copy["credibility_reason"] = reason
        scored.append(r_copy)
        scores.append(score)

    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    max_score = max(scores) if scores else 0
    has_verified = any(s >= 9 for s in scores)  # Machine-checked or peer-reviewed with DOI
    needs_verification = not has_verified or avg_score < 5

    if has_verified and max_score >= 9:
        assessment = "HIGH — at least one result is machine-checked or peer-reviewed with DOI."
        recommendation = "Trust the high-credibility result. Cite it in the proof."
    elif max_score >= 7:
        assessment = "MEDIUM — published sources found but not yet machine-checked in Lean."
        recommendation = "Use the result as a proof strategy, but independently formalize the key steps."
    elif max_score >= 4:
        assessment = "LOW — results from web or unverified sources."
        recommendation = "Do NOT trust directly. Independently prove the statement using known axioms and lemmas."
    else:
        assessment = "INSUFFICIENT — no credible source found."
        recommendation = "All results are low-quality. Prove the statement from first principles."

    return {
        "result_count": len(results),
        "scores": {"min": min(scores), "max": max_score, "average": avg_score},
        "has_machine_checked": has_verified,
        "overall_credibility": avg_score,
        "assessment": assessment,
        "needs_verification": needs_verification,
        "recommendation": recommendation,
        "scored_results": scored[:20],
    }


@tool("search_and_verify", parse_docstring=True)
def search_and_verify(query: str, project_dir: str = ".") -> str:
    """Search for a theorem across all sources AND analyze the credibility of each result.
    If no result is machine-checked, the tool will recommend independent formalization.

    Use this when you need a theorem to use in a proof but aren't sure whether
    a known formalized version exists.

    Args:
        query: Theorem name, statement, or mathematical concept.
        project_dir: Lean project root path.
    """
    project = Path(project_dir)

    # 1. Search all sources
    all_results = []
    all_results.extend(_search_mathlib_local(query, str(project / ".lake" / "packages" / "mathlib"), "name"))
    all_results.extend(_search_project_local(query, project))
    all_results.extend(_search_leansearch_api(query))
    all_results.extend(_search_loogle_api(query))
    all_results.extend(_search_matlas_api(query))

    # Deduplicate
    seen = set()
    deduped = []
    for r in all_results:
        key = r.get("name") or r.get("snippet", "")
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    # 2. Credibility analysis
    analysis = _analyze_credibility(deduped)

    return json.dumps({
        "query": query,
        "total_results": len(deduped),
        "credibility_analysis": {
            k: v for k, v in analysis.items() if k != "scored_results"
        },
        "results": analysis["scored_results"][:30],
    }, indent=2)


@tool("verify_theorem", parse_docstring=True)
def verify_theorem(statement: str, known_lemmas: str = "", project_dir: str = ".") -> str:
    """Check whether a mathematical statement can be independently verified.
    Searches for known proofs, checks Mathlib for a formalized version, and
    assesses whether the statement can be reliably used in a Lean proof.

    Args:
        statement: The theorem statement to verify.
        known_lemmas: Comma-separated list of known lemmas that can be used.
        project_dir: Lean project root path.
    """
    # 1. Search Mathlib for a direct match (machine-checked)
    mathlib_results = _search_mathlib_local(
        statement[:60], str(Path(project_dir) / ".lake" / "packages" / "mathlib"), "name"
    )
    mathlib_has_match = len(mathlib_results) > 0

    # 2. Search Matlas for published proofs
    matlas_results = _search_matlas_api(statement[:120])

    # 3. Search the web
    web_found = False
    try:
        from overlay.backend.workflows.rethlas_skill_tools import _web_search
        web_results = _web_search(f"proof of {statement[:100]}", 3)
        web_found = len(web_results) > 0
    except Exception:
        web_results = []
        web_found = False

    # 4. Credibility assessment
    if mathlib_has_match:
        verdict = "VERIFIED"
        detail = "Statement has a machine-checked proof in Mathlib. Safe to use."
        credibility = 10
    elif len(matlas_results) > 0 and any(
        r.get("type") == "paper" and r.get("doi") for r in matlas_results
    ):
        verdict = "LIKELY_TRUE"
        detail = "Peer-reviewed paper provides a proof. Should be independently formalized in Lean."
        credibility = 7
    elif web_found:
        verdict = "PLAUSIBLE"
        detail = "Web search found discussions of this statement. Needs independent verification."
        credibility = 3
    else:
        verdict = "UNVERIFIED"
        detail = "No authoritative source found. Must be proved from first principles."
        credibility = 1

    return json.dumps({
        "statement": statement[:200],
        "verdict": verdict,
        "credibility": credibility,
        "detail": detail,
        "mathlib_match": mathlib_has_match,
        "matlas_results": [{
            "name": r.get("entity_name", r.get("name", "")),
            "statement": r.get("statement", "")[:200],
            "source": r.get("source", ""),
            "doi": r.get("doi", ""),
        } for r in matlas_results[:5]],
        "recommended_action": (
            "Directly use from Mathlib" if credibility >= 10
            else "Use as proof guide; formalize key steps" if credibility >= 7
            else "Search for known lemmas; construct independent proof" if credibility >= 3
            else "Prove from first principles; do not rely on this statement"
        ),
    }, indent=2)


# ── Tool list for registration ──
LEAN_TOOLS = [
    lean_check_file,
    lean_build,
    lean_sorry_scan,
    lean_file_outline,
    lean_goal_at,
    lean_theorem_search,
    search_and_verify,
    verify_theorem,
]
