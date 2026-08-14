"""StateGraph node functions.

Each node is an ``async`` callable ``(TutorState) -> dict``. The returned dict
is a *partial* update — only the keys it contains are merged back into state by
LangGraph.

Pipeline::

    assess  →  router  →  execute  →  observe  ─┐
                   ↑                            │
                   └──── should_continue ───────┘
                                                │
                                             update → END
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.engine.state import TutorState
from app.skills.loader import SkillLoader
from app.skills.catalog import SkillCatalog
from app.skills.runner import render_prompt, _extract_json_block
from app.skills.schema import SkillMeta

logger = logging.getLogger("edu-agent.engine")

# Guard rail: never loop the assess→observe cycle more than this many times.
MAX_ITERATIONS = 3

# ── Module-level skill singletons (loaded once) ────────────────────

_loader: SkillLoader | None = None
_catalog: SkillCatalog | None = None


def _get_catalog() -> tuple[SkillLoader, SkillCatalog]:
    """Lazily load skills once and cache as a module-level singleton."""
    global _loader, _catalog
    if _catalog is None:
        _loader = SkillLoader()
        _catalog = SkillCatalog(_loader.load_directory("../skills"))
        logger.info("Loaded %d skills into catalog", _catalog.size)
    return _loader, _catalog  # type: ignore[return-value]


def _get_skill(name: str) -> SkillMeta | None:
    """Fetch a skill by name from the cached catalog."""
    _, catalog = _get_catalog()
    return catalog.get(name)


async def _llm_json(skill: SkillMeta, state: dict[str, Any]) -> dict | None:
    """Render a skill template, call the LLM, and parse JSON from the reply."""
    from app.engine.llm import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    prompt = render_prompt(skill, state)
    sys_msg = skill.system_prompt or (
        "You are a K12 tutoring system component. Respond with ONLY valid JSON."
    )
    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content=sys_msg),
        HumanMessage(content=prompt),
    ])
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        raw = "".join(
            part if isinstance(part, str) else str(getattr(part, "text", part))
            for part in raw
        )
    return _extract_json_block(raw)


# ── Nodes ──────────────────────────────────────────────────────────


async def assess_node(state: TutorState) -> dict[str, Any]:
    """Assess the student profile from DB and analyze the current emotion.

    Two responsibilities:
    1. Load the persisted StudentProfile (mastery, ability, style, mistakes).
    2. Run the ``emotion-analyzer`` meta-skill (single LLM call) to score the
       latest message along four emotion dimensions, so ``router_node`` can
       apply the emotion short-circuit.
    """
    iteration = state.get("iteration_count", 0)
    student_id = state.get("student_id", "")
    messages = state.get("messages", [])
    user_text = ""
    if messages:
        last = messages[-1]
        user_text = getattr(last, "content", "") or ""

    logger.info(
        "assess_node: student=%s subject=%s grade=%s iteration=%d",
        student_id, state.get("subject"), state.get("grade"), iteration,
    )

    # 1. Load persisted profile
    profile_data: dict[str, Any] = {}
    if student_id:
        try:
            from app.database import async_session
            from app.profile.store import profile_store

            async with async_session() as db:
                profile = await profile_store.load(db, student_id)
                profile_data = profile.to_state_dict()
        except Exception as e:
            logger.warning("assess_node: could not load profile (%s)", e)

    update: dict[str, Any] = {"iteration_count": iteration + 1}
    if profile_data:
        for key in ("knowledge_mastery", "emotion_state", "ability_level",
                     "learning_style", "recent_mistakes", "grade"):
            val = profile_data.get(key)
            if val is not None:
                update[key] = val

    # 2. Emotion analysis via LLM (merged into assess — no separate call site)
    if user_text:
        try:
            analyzer = _get_skill("emotion-analyzer")
            if analyzer is not None:
                emotion_state = {
                    "student_message": user_text,
                    "recent_mistakes": profile_data.get("recent_mistakes", []),
                }
                result = await _llm_json(analyzer, emotion_state)
                if result and isinstance(result, dict):
                    # Only keep the four numeric dimensions
                    merged_emotion: dict[str, float] = {}
                    for dim in ("frustration", "confusion", "excitement", "confidence"):
                        val = result.get(dim)
                        if isinstance(val, (int, float)):
                            merged_emotion[dim] = float(val)
                    if merged_emotion:
                        update["emotion_state"] = merged_emotion
                        logger.info(
                            "assess_node: emotion=%s", merged_emotion
                        )
        except Exception as e:
            logger.warning("assess_node: emotion analysis failed (%s)", e)

    return update


async def router_node(state: TutorState) -> dict[str, Any]:
    """Select which skill should handle this turn.

    1. Emotion short-circuit: frustration > 0.7 → ``emotion-respond``.
    2. Otherwise delegate to the ``skill-selector`` meta-skill (LLM call) that
       picks from the catalog, filtered by subject.
    3. Fallback to ``concept-explain`` if the LLM decision is invalid.
    """
    emotion = state.get("emotion_state", {}) or {}
    frustration = float(emotion.get("frustration", 0.0))
    confusion = float(emotion.get("confusion", 0.0))

    # 1. Emotion short-circuit
    if frustration > 0.7 or confusion > 0.8:
        logger.info(
            "router_node: emotion short-circuit (frustration=%.2f confusion=%.2f) → emotion-respond",
            frustration, confusion,
        )
        return {
            "selected_skill": "emotion-respond",
            "skill_layer": "atom",
            "skill_params": {},
        }

    # 2. LLM-driven routing via skill-selector
    try:
        selector = _get_skill("skill-selector")
        if selector is not None:
            _, catalog = _get_catalog()
            subject = state.get("subject", "math")

            # Build menu: exclude meta skills (system internals), keep approved
            available_skills = [
                {"id": s.id, "description": s.description}
                for s in catalog.all
                if s.category != "meta" and s.status == "approved"
            ]

            messages = state.get("messages", [])
            user_text = ""
            if messages:
                last = messages[-1]
                user_text = getattr(last, "content", "") or ""

            decision = await _llm_json(selector, {
                "student_message": user_text,
                "subject": subject,
                "grade": state.get("grade", 7),
                "ability_level": state.get("ability_level", "beginner"),
                "emotion_state": emotion,
                "recent_mistakes": state.get("recent_mistakes", []),
                "available_skills": available_skills,
            })

            if decision and isinstance(decision, dict):
                selected = str(decision.get("selected_skill", "")).strip()
                layer = str(decision.get("skill_layer", "atom")).strip()
                params = decision.get("skill_params") or {}

                # Validate against catalog
                valid_ids = {s.id for s in catalog.all}
                if selected and selected in valid_ids:
                    logger.info(
                        "router_node: LLM selected %s (layer=%s, reason=%s)",
                        selected, layer, decision.get("reason", ""),
                    )
                    return {
                        "selected_skill": selected,
                        "skill_layer": layer if layer in ("atom", "molecule", "compound") else "atom",
                        "skill_params": params if isinstance(params, dict) else {},
                    }
                logger.warning(
                    "router_node: LLM returned invalid skill %r, falling back", selected
                )
    except Exception as e:
        logger.warning("router_node: skill-selector failed (%s), falling back", e)

    # 3. Fallback
    logger.info("router_node: fallback → concept-explain")
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

    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    user_text = getattr(last_message, "content", str(last_message)) if last_message else ""

    # Try to load the skill and render its template
    try:
        from app.skills.runner import run_atom

        skill_meta = _get_skill(skill_name)
        if skill_meta is not None:
            from app.engine.llm import get_llm
            llm = get_llm()

            # Inject the student message + problem context into the template
            # context so skill bodies can reference {{ student_message }} etc.
            skill_state = dict(state)
            skill_state["student_message"] = user_text
            skill_state["problem_context"] = user_text
            params = state.get("skill_params") or {}
            if isinstance(params, dict):
                skill_state["concept_id"] = params.get("concept_id", "")
                skill_state["problem_context"] = params.get("problem_context", "") or user_text

            result = await run_atom(skill_meta, skill_state, llm)
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
    """Persist the teaching event and update the student profile.

    Writes knowledge_delta to the student's profile, appends the current
    emotion signal to the emotion history, and logs a TeachingEvent row.
    """
    student_id = state.get("student_id", "")
    skill = state.get("selected_skill", "unknown")
    comprehension = state.get("comprehension_signal", "no_response")
    delta = state.get("knowledge_delta", {})

    logger.info(
        "update_node: persisting student=%s skill=%s comprehension=%s",
        student_id, skill, comprehension,
    )

    if student_id:
        try:
            from app.database import async_session
            from app.profile.store import profile_store

            async with async_session() as db:
                profile = await profile_store.load(db, student_id)

                # Apply knowledge deltas
                if delta:
                    for kp_id, change in delta.items():
                        if isinstance(change, dict):
                            score = change.get("mastery", 0)
                        elif isinstance(change, (int, float)):
                            score = float(change)
                        else:
                            continue
                        profile.update_mastery(kp_id, score - profile.knowledge_mastery.get(kp_id, 0))

                # Map comprehension to emotion update
                emotion_map = {
                    "understood": {"confidence": 0.8, "frustration": 0.1, "confusion": 0.1},
                    "confused": {"confusion": 0.7, "frustration": 0.3},
                    "partial": {"confusion": 0.4, "confidence": 0.4},
                }
                emotion_update = emotion_map.get(comprehension, {})
                if emotion_update:
                    profile.emotion_history.append(emotion_update)
                    profile.emotion_history = profile.emotion_history[-20:]  # keep last 20

                await profile_store.save(db, profile)

            # Auto-record mistake when student is confused or made an error
            if comprehension in ("confused", "partial"):
                try:
                    from app.models import MistakeEntryDB
                    messages_list = state.get("messages", [])
                    user_msg = ""
                    for m in reversed(messages_list):
                        role = getattr(m, "type", "") or getattr(m, "role", "")
                        if role in ("human", "user"):
                            user_msg = getattr(m, "content", "")[:2000]
                            break

                    skill_output = (state.get("skill_output") or "")[:5000]
                    async with async_session() as mistake_db:
                        mistake = MistakeEntryDB(
                            user_id=uuid.UUID(student_id),
                            subject=state.get("subject", "math"),
                            question=user_msg or "(empty message)",
                            correct_answer=skill_output or None,
                            explanation=f"Student was {comprehension}. Skill: {skill}",
                            source="chat",
                        )
                        mistake_db.add(mistake)
                        await mistake_db.commit()
                        logger.info(
                            "update_node: auto-recorded mistake #%d (comprehension=%s)",
                            mistake.id, comprehension,
                        )
                except Exception as me:
                    logger.warning("update_node: could not record mistake (%s)", me)

        except Exception as e:
            logger.warning("update_node: could not save profile (%s)", e)

    return {}
