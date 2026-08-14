"""LangGraph engine layer for the edu-agent K12 tutoring platform.

This package assembles the core tutoring state machine:

    START → assess → router → execute → observe → (router | update) → END

Public API:
    from app.engine import tutor_app, build_tutor_graph, TutorState
"""

from app.engine.graph import build_tutor_graph, tutor_app
from app.engine.state import TutorState

__all__ = ["build_tutor_graph", "tutor_app", "TutorState"]
