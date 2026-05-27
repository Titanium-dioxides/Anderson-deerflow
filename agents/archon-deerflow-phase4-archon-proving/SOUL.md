---
name: archon-deerflow-phase4-archon-proving
description: Plan Agent → Parallel Lean Agents → Reviewer → Review Agent. Fills sorry placeholders with Lean proofs using LSP tools and theorem search.
---

# Archon Phase 4 — Proving Loop

Fill sorry placeholders in Lean files.

**Agent structure:**
- Plan Agent: Analyze state, choose focus files, define strategy
- Lean Agents: Parallel workers with LSP tools (check, outline, goal, search)
- Reviewer: Analyze attempts and failures
- Review Agent: Cross-session strategist, reroute from dead ends

**Tools:** lean_check_file, lean_file_outline, lean_sorry_scan, lean_goal_at, lean_theorem_search, lean_build
