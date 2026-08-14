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

    Renders the skill prompt template with current state, calls the LLM,
    and returns the response along with a comprehension heuristic.
    Falls back to a simple direct LLM call if the skill is not found.
    """
    skill_name = state.get("selected_skill", "concept-explain")
    logger.info("execute_node: skill=%s", skill_name)

    # Build the LLM prompt
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    user_text = getattr(last_message, "content", str(last_message)) if last_message else ""

    # Try to load the skill and render its template
    try:
        from app.skills.loader import SkillLoader
        from app.skills.runner import run_atom

        loader = SkillLoader()
        skills = loader.load_directory("../skills")
        skill_meta = next((s for s in skills if s.name == skill_name), None)

        if skill_meta:
            from app.engine.llm import get_llm
            llm = get_llm()
            result = await run_atom(skill_meta, state, llm)
            logger.info("execute_node: skill=%s comprehension=%s", skill_name, result.comprehension)
            return {
                "skill_output": result.output,
                "comprehension_signal": result.comprehension,
                "knowledge_delta": result.knowledge_delta,
            }
    except Exception as e:
        logger.warning("execute_node: skill execution failed (%s), falling back to direct LLM", e)

    # Fallback: direct LLM call without skill template
    try:
        from app.engine.llm import get_llm
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = get_llm()
        system = SystemMessage(content=(
            "You are a helpful K12 tutor. Explain clearly in Chinese (简体中文). "
            "Use Markdown formatting. For math, use LaTeX ($...$ inline, $$...$$ block). "
            "Keep explanations concise and age-appropriate."
        ))
        human = HumanMessage(content=user_text)
        response = await llm.ainvoke([system, human])
        output = response.content if hasattr(response, "content") else str(response)
        return {
            "skill_output": output,
            "comprehension_signal": "understood",
            "knowledge_delta": {},
        }
    except Exception as e:
        logger.error("execute_node: LLM call failed: %s", e)
        return {
            "skill_output": f"抱歉，处理时出现了错误：{e}",
            "comprehension_signal": "understood",  # Stop the loop even on error
            "knowledge_delta": {},
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
