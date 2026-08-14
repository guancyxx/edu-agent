"""Assemble and compile the LangGraph tutoring state machine.

Topology::

    START → assess → router → execute → observe ─┐
                       ↑                         │ should_continue
                       └─────────────────────────┘
                                                 │ !should_continue
                                              update → END

The compiled graph is exposed both as a factory (:func:`build_tutor_graph`)
and as a module-level singleton (:data:`tutor_app`). The singleton is built
inside a ``try/except`` so that importing this module never hard-fails when
LangGraph is not yet installed (e.g. during early development or in CI that
only needs type checking).
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.engine.nodes import (
    assess_node,
    execute_node,
    observe_node,
    router_node,
    update_node,
)
from app.engine.state import TutorState

logger = logging.getLogger("edu-agent.engine")


def build_tutor_graph():
    """Build and compile the tutoring ``StateGraph``.

    Returns
    -------
    CompiledGraph
        A runnable LangGraph compiled application.
    """
    graph: StateGraph = StateGraph(TutorState)

    # --- nodes ---
    graph.add_node("assess", assess_node)
    graph.add_node("router", router_node)
    graph.add_node("execute", execute_node)
    graph.add_node("observe", observe_node)
    graph.add_node("update", update_node)

    # --- linear edges ---
    graph.add_edge(START, "assess")
    graph.add_edge("assess", "router")
    graph.add_edge("router", "execute")
    graph.add_edge("execute", "observe")

    # --- conditional edge: loop or finish ---
    graph.add_conditional_edges(
        "observe",
        lambda s: "router" if s.get("should_continue") else "update",
        {"router": "router", "update": "update"},
    )

    graph.add_edge("update", END)

    return graph.compile()


# Module-level singleton. Wrapped so that importing this package never raises
# even when langgraph isn't installed yet.
try:
    tutor_app = build_tutor_graph()
except Exception as exc:  # pragma: no cover - import-time guard
    logger.warning("Failed to compile tutor graph: %s", exc)
    tutor_app = None  # type: ignore[assignment]
