"""
Bridge module for LangGraph Studio (langgraph dev).

Exposes our Phase 1-6 graph builders in the format that LangGraph Studio
expects: each builder returns a CompiledStateGraph.
"""

import os
import sys

# Ensure our overlay workflows are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "overlay", "backend"))

from workflows.phase1_runtime import build_phase1_graph
from workflows.phase2_rethlas import build_phase2_rethlas_graph
from workflows.phase3_archon_scaffolding import build_phase3_archon_scaffolding_graph
from workflows.phase4_archon_proving import build_phase4_archon_proving_graph
from workflows.phase5_polish import build_phase5_polish_graph
from workflows.phase6_e2e import build_phase6_e2e_graph


def build_phase1():
    return build_phase1_graph()


def build_phase2():
    return build_phase2_rethlas_graph()


def build_phase3():
    return build_phase3_archon_scaffolding_graph()


def build_phase4():
    return build_phase4_archon_proving_graph()


def build_phase5():
    return build_phase5_polish_graph()


def build_phase6():
    return build_phase6_e2e_graph()


def make_checkpointer():
    """Return None — LangGraph Studio will use in-memory checkpointer."""
    return True  # True = use default in-memory checkpointer


async def noop_auth(request):
    """No-op auth for LangGraph Studio local dev."""
    return None
