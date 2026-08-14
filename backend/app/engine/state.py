"""TutorState — the central TypedDict that flows through the LangGraph.

Every node receives a (read-only) snapshot of this state and returns a *partial*
dict of the fields it wants to update; LangGraph merges them back automatically.

Design notes
------------
* ``messages`` uses the LangGraph reducer pattern so new messages are appended
  rather than replacing the whole history.
* Emotion and mastery values are floats in ``[0.0, 1.0]``.
* ``knowledge_delta`` captures the change in mastery produced during a single
  graph run, so ``update_node`` can persist it to the student profile.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage


class TutorState(TypedDict):
    """Typed dictionary representing the full tutoring session state.

    Attributes
    ----------
    messages:
        Conversation history. The ``add`` reducer appends new messages on each
        node update instead of overwriting.
    student_id:
        Unique identifier of the student the graph is serving.
    role:
        Who is interacting with the tutor — drives access control and tone.
    subject:
        Curriculum subject, e.g. ``"math"`` or ``"english"``.
    grade:
        K12 grade level (1–12).
    knowledge_mastery:
        Mapping of knowledge-point id → mastery score in ``[0.0, 1.0]``.
    emotion_state:
        Detected emotion intensities. Keys: ``frustration``, ``confusion``,
        ``confidence``, ``excitement``; values in ``[0.0, 1.0]``.
    ability_level:
        Coarse ability bucket used by the skill router.
    learning_style:
        Preferred pedagogical entry point.
    recent_mistakes:
        Sliding window of the student's most recent errors (max ~10).
    selected_skill:
        The skill id chosen by ``router_node`` for the current turn.
    skill_params:
        Parameters to pass into the selected skill at execution time.
    skill_layer:
        Complexity tier of ``selected_skill``.
    skill_output:
        Raw output produced by ``execute_node`` (skill result).
    comprehension_signal:
        How well the student understood the last skill output.
    knowledge_delta:
        Mastery changes computed this run, keyed by knowledge-point id.
    should_continue:
        Whether the graph should loop back to ``router`` after ``observe``.
    iteration_count:
        Number of assess→router→execute→observe cycles completed so far.
    """

    # --- conversation ---
    messages: Annotated[list[BaseMessage], add]

    # --- student identity & context ---
    student_id: str
    role: Literal["student", "parent", "teacher"]
    subject: str
    grade: int

    # --- student profile (dynamic) ---
    knowledge_mastery: dict[str, float]
    emotion_state: dict[str, float]
    ability_level: Literal["beginner", "intermediate", "advanced"]
    learning_style: Literal["example_first", "theory_first", "practice_first"]
    recent_mistakes: list[dict]

    # --- routing / execution ---
    selected_skill: str
    skill_params: dict
    skill_layer: Literal["atom", "molecule", "compound"]
    skill_output: str

    # --- observation / feedback ---
    comprehension_signal: Literal[
        "understood", "confused", "partial", "no_response"
    ]
    knowledge_delta: dict

    # --- loop control ---
    should_continue: bool
    iteration_count: int
