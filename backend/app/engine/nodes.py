"""StateGraph node functions.

Each node is an ``async`` callable ``(TutorState) -> dict``. The returned dict
is a *partial* update — only the keys it contains are merged back into state by
LangGraph. Nodes intentionally keep side-effects minimal: they read state,
compute the next update, and leave persistence to ``update_node``.

Pipeline::

    assess  →  router  →  execute  →  observe  ─┐
                   ↑                            │
                   └──── should_continue ───────┘
                                                │
                                             update → END
"""

from __future__ import annotations

import logging
from typing import Any

from app.engine.state import TutorState

logger = logging.getLogger("edu-agent.engine")

# Guard rail: never loop the assess→observe cycle more than this many times.
MAX_ITERATIONS = 3


async def assess_node(state: TutorState) -> dict[str, Any]:
    """Assess the student's current profile from the latest messages.

    Placeholder implementation: logs the assessment entry point and bumps the
    iteration counter so the graph can enforce a max-iterations guard.

    Parameters
    ----------
    state:
        Current tutoring state (read-only snapshot).

    Returns
    -------
    dict
        Partial update containing the incremented ``iteration_count``.
    """
    iteration = state.get("iteration_count", 0)
    logger.info(
        "assess_node: student=%s subject=%s grade=%s iteration=%d",
        state.get("student_id"),
        state.get("subject"),
        state.get("grade"),
        iteration,
    )
    return {"iteration_count": iteration + 1}


async def router_node(state: TutorState) -> dict[str, Any]:
    """Decide which skill to execute next.

    Implements an *emotion short-circuit*: when ``frustration`` exceeds 0.7 the
    router immediately selects the ``emotion-respond`` atom skill, bypassing
    the normal pedagogical routing. Otherwise it falls back to a placeholder
    selection of ``concept-explain``.

    Parameters
    ----------
    state:
        Current tutoring state.

    Returns
    -------
    dict
        Partial update with ``selected_skill``, ``skill_layer``, and
        ``skill_params``.
    """
    emotion = state.get("emotion_state", {}) or {}
    frustration = emotion.get("frustration", 0.0)

    if frustration > 0.7:
        logger.info(
            "router_node: frustration=%.2f → emotion-respond", frustration
        )
        return {
            "selected_skill": "emotion-respond",
            "skill_layer": "atom",
            "skill_params": {},
        }

    logger.info("router_node: frustration=%.2f → concept-explain", frustration)
    return {
        "selected_skill": "concept-explain",
        "skill_layer": "atom",
        "skill_params": {},
    }


async def execute_node(state: TutorState) -> dict[str, Any]:
    """Execute the selected skill and capture its output.

    Placeholder: returns a sentinel output and a ``no_response`` comprehension
    signal. The real implementation will dispatch to the SkillRunner based on
    ``selected_skill`` and ``skill_layer``.

    Returns
    -------
    dict
        Partial update with ``skill_output`` and ``comprehension_signal``.
    """
    skill = state.get("selected_skill", "<none>")
    layer = state.get("skill_layer", "<none>")
    logger.info("execute_node: skill=%s layer=%s", skill, layer)
    return {
        "skill_output": "[skill execution placeholder]",
        "comprehension_signal": "no_response",
    }


async def observe_node(state: TutorState) -> dict[str, Any]:
    """Observe the student's comprehension and decide whether to continue.

    Continuation rules (all must favour stopping the loop):
    * If the student understood the last output → stop (``should_continue=False``).
    * If the max iteration count has been reached → stop.
    * Otherwise → loop back to ``router`` for another attempt.

    Returns
    -------
    dict
        Partial update with ``should_continue``.
    """
    signal = state.get("comprehension_signal", "no_response")
    iteration = state.get("iteration_count", 0)

    if signal == "understood":
        logger.info("observe_node: understood at iteration=%d → stop", iteration)
        return {"should_continue": False}

    if iteration >= MAX_ITERATIONS:
        logger.info(
            "observe_node: max iterations (%d) reached → stop", MAX_ITERATIONS
        )
        return {"should_continue": False}

    logger.info(
        "observe_node: signal=%s iteration=%d → continue", signal, iteration
    )
    return {"should_continue": True}


async def update_node(state: TutorState) -> dict[str, Any]:
    """Persist the teaching event and close out the graph run.

    Placeholder: logs a summary of what happened during this run. The real
    implementation will write a ``TeachingEvent`` row and update the student
    profile with ``knowledge_delta``.

    Returns
    -------
    dict
        Empty dict — no further state changes are needed at the end of the run.
    """
    logger.info(
        "update_node: persisting teaching event student=%s skill=%s "
        "iterations=%d comprehension=%s",
        state.get("student_id"),
        state.get("selected_skill"),
        state.get("iteration_count"),
        state.get("comprehension_signal"),
    )
    return {}
