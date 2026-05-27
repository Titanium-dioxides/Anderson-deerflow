#!/usr/bin/env python3
"""Generate Mermaid diagrams for all Phase graphs."""

GRAPHS = {
    "Phase 1 — Workspace Bootstrap": [
        ("bootstrap_layout", "END"),
    ],
    "Phase 2 — Rethlas Dual Agent": [
        ("bootstrap_layout", "init_rethlas_memory"),
        ("init_rethlas_memory", "generation_agent"),
        ("generation_agent", "verification_agent"),
        ("verification_agent", "END"),
    ],
    "Phase 3 — Archon Scaffolding": [
        ("bootstrap_layout", "references_ingestion"),
        ("references_ingestion", "project_init"),
        ("project_init", "autoformalize"),
        ("autoformalize", "module_split"),
        ("module_split", "manifest"),
        ("manifest", "END"),
    ],
    "Phase 4 — Archon Proving Loop": [
        ("bootstrap_layout", "phase3_sync"),
        ("phase3_sync", "plan_agent"),
        ("plan_agent", "lean_agents"),
        ("lean_agents", "reviewer"),
        ("reviewer", "review_agent"),
        ("review_agent", "plan_agent::loop"),
        ("review_agent", "END::complete"),
    ],
    "Phase 5 — Polish & Export": [
        ("bootstrap_layout", "phase4_sync"),
        ("phase4_sync", "sorry_axiom_check"),
        ("sorry_axiom_check", "compile_check"),
        ("compile_check", "polish_agent"),
        ("polish_agent", "artifact_pack"),
        ("artifact_pack", "export_outputs"),
        ("export_outputs", "history_align"),
        ("history_align", "manifest"),
        ("manifest", "END"),
    ],
    "Phase 6 — E2E Pipeline": [
        ("e2e_run::P1→P2→P3→P4→P5", "e2e_verify"),
        ("e2e_verify", "END"),
    ],
}

if __name__ == "__main__":
    for name, edges in GRAPHS.items():
        print(f"\n## {name}")
        print("```mermaid")
        print("graph LR")
        for src, dst in edges:
            safe_src = src.replace("::", "_").replace(" ", "_")
            safe_dst = dst.replace("::", "_").replace(" ", "_")
            label = ""
            if "::" in dst:
                dst_name, label = dst.split("::", 1)
                safe_dst = dst_name
            print(f"    {safe_src} -->|{label}| {safe_dst}" if label else f"    {safe_src} --> {safe_dst}")
        print("```")
