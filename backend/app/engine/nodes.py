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

    # Seed 0, not 1: router_node bumps the counter before every execute, so
    # after N executes the counter == N and observe_node's
    # ``iteration >= MAX_ITERATIONS`` guard stops the loop after exactly
    # MAX_ITERATIONS execute attempts (audit fix, PR #11).
    update: dict[str, Any] = {"iteration_count": iteration}
    if profile_data:
        for key in ("knowledge_mastery", "emotion_state", "ability_level",
                     "learning_style", "recent_mistakes", "grade"):
            val = profile_data.get(key)
            if val is not None:
                update[key] = val

    # 1.5 Curriculum anchoring: load the grade's knowledge tree and compute
    # weak knowledge points (pure deterministic code, no LLM).
    subject = str(state.get("subject", "math"))
    grade = update.get("grade") or state.get("grade") or 7
    try:
        from app.curriculum import get_index

        index = get_index()
        chapters = index.list_by_grade(subject, int(grade))
        kps = [kp for ch in chapters for kp in ch.knowledge_points]
        if kps:
            kp_ids = {kp.id for kp in kps}
            update["curriculum_kps"] = [
                {
                    "id": kp.id,
                    "title": kp.title,
                    "difficulty": kp.difficulty,
                    "description": kp.description,
                    "prerequisites": kp.prerequisites,
                }
                for kp in kps
            ]
            mastery = update.get(
                "knowledge_mastery", state.get("knowledge_mastery", {})
            ) or {}

            def _prereqs_ok(kp) -> bool:
                # Prerequisites outside the loaded tree belong to earlier
                # grades — assume covered unless mastery says otherwise.
                return all(
                    mastery.get(p, 0.0) >= 0.6
                    for p in kp.prerequisites
                    if p in kp_ids
                )

            weak = [
                kp for kp in kps
                if mastery.get(kp.id, 0.0) < 0.6 and _prereqs_ok(kp)
            ]
            weak.sort(key=lambda kp: (mastery.get(kp.id, 0.0), kp.difficulty))
            update["weak_kps"] = [
                {
                    "id": kp.id,
                    "title": kp.title,
                    "difficulty": kp.difficulty,
                    "description": kp.description,
                }
                for kp in weak[:8]
            ]
            logger.info(
                "assess_node: curriculum %s-%d: %d KPs, %d weak",
                subject, int(grade), len(kps), len(weak),
            )
    except Exception as e:
        logger.warning("assess_node: curriculum anchoring failed (%s)", e)

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
    """Public router entry: delegates to ``_router_node_inner`` and bumps the
    loop-cycle counter so ``observe_node``'s MAX_ITERATIONS guard can fire.

    assess_node seeds the counter at 0; every router visit bumps it before
    the upcoming execute, so the counter always equals the number of execute
    attempts completed and observe_node stops the loop after exactly
    MAX_ITERATIONS attempts. Without this bump the loop edge (observe→router)
    never revisits assess and the guard never triggers (GraphRecursionError
    at LangGraph's limit — live-proven 2026-08-24).
    """
    update = await _router_node_inner(state)
    update["iteration_count"] = state.get("iteration_count", 0) + 1
    return update


async def _router_node_inner(state: TutorState) -> dict[str, Any]:
    """Select which skill should handle this turn.

    1. Visual-request short-circuit: explicit "draw me a picture" phrasing →
       ``picture-explain`` (a confused student asking for a diagram gets the
       diagram — the picture IS the confusion-recovery tool, so this outranks
       the emotion gate).
    2. Emotion short-circuit: frustration > 0.7 → ``emotion-respond``.
    3. Otherwise delegate to the ``skill-selector`` meta-skill (LLM call) that
       picks from the catalog, filtered by subject.
    4. Fallback to ``concept-explain`` if the LLM decision is invalid.
    """
    emotion = state.get("emotion_state", {}) or {}
    frustration = float(emotion.get("frustration", 0.0))
    confusion = float(emotion.get("confusion", 0.0))

    # 1. Deterministic picture-explain short-circuit: an explicit visual request
    # (画个图/图解/看图讲) routes straight to picture-explain instead of gambling
    # on the LLM selector picking it from a text-only description. Runs BEFORE the
    # emotion gate on purpose (audit note, PR #3): a student with confusion > 0.8
    # who explicitly asks for a picture wants the picture.
    _message = ""
    _msgs = state.get("messages") or []
    if _msgs:
        _last = _msgs[-1]
        _content: object = (
            getattr(_last, "content", _last) if not isinstance(_last, dict)
            else _last.get("content", _last.get("text", ""))
        )
        if isinstance(_content, list):
            # multimodal parts: dicts with type/text (or image_url), or plain strings
            parts: list[str] = []
            for p in _content:
                if isinstance(p, dict):
                    parts.append(str(p.get("text") or p.get("content") or ""))
                else:
                    parts.append(str(p))
            _message = " ".join(parts)
        else:
            _message = str(_content)
    if any(kw in _message for kw in ("画个图", "画图", "图解", "看图讲", "图说明", "eli5", "ELI5")):
        logger.info("router_node: visual-request short-circuit → picture-explain")
        return {
            "selected_skill": "picture-explain",
            "skill_layer": "atom",
            "skill_params": {},
        }

    # 2. Emotion short-circuit
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

    # 3. LLM-driven routing via skill-selector
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
                "curriculum_kps": state.get("curriculum_kps", []),
                "weak_kps": state.get("weak_kps", []),
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
                    # Deterministic concept_id validation against the real
                    # curriculum ids — never trust the LLM on this. When no
                    # tree is loaded (empty list) keep the LLM's value: it is
                    # advisory prompt context, not persisted data.
                    params = dict(params) if isinstance(params, dict) else {}
                    raw_concept = str(params.get("concept_id", "") or "").strip()
                    valid_kp_ids = {
                        kp["id"] for kp in state.get("curriculum_kps", [])
                    }
                    if raw_concept and valid_kp_ids and raw_concept not in valid_kp_ids:
                        logger.warning(
                            "router_node: concept_id %r not in curriculum, dropped",
                            raw_concept,
                        )
                        params["concept_id"] = ""
                    return {
                        "selected_skill": selected,
                        "skill_layer": layer if layer in ("atom", "molecule", "compound") else "atom",
                        "skill_params": params,
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
        from app.skills.runner import run

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

            result = await run(skill_meta, skill_state, llm)
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

                # Apply knowledge deltas — whitelist keys against the real
                # curriculum. Invalid keys are dropped and logged; an empty
                # index (no tree for this subject/grade) drops everything,
                # by design: unvalidated keys are worse than no data.
                if delta:
                    from app.curriculum import get_index

                    index = get_index()
                    for kp_id, change in delta.items():
                        kp = index.get_kp(str(kp_id))
                        if kp is None:
                            logger.warning(
                                "update_node: dropped knowledge_delta key %r (not a curriculum id)",
                                kp_id,
                            )
                            continue
                        if isinstance(change, dict):
                            raw_score = change.get("mastery")
                        elif isinstance(change, (int, float)) and not isinstance(change, bool):
                            raw_score = change
                        else:
                            logger.warning(
                                "update_node: skipped knowledge_delta[%r] (unsupported type %s)",
                                kp_id, type(change).__name__,
                            )
                            continue
                        try:
                            score = float(raw_score)  # type: ignore[arg-type]
                        except (TypeError, ValueError):
                            logger.warning(
                                "update_node: skipped knowledge_delta[%r] (non-numeric mastery %r)",
                                kp_id, raw_score,
                            )
                            continue
                        score = max(0.0, min(1.0, score))
                        # Value semantics: the KP's latest mastery level.
                        profile.knowledge_mastery[kp.id] = score
                        logger.info(
                            "update_node: mastery[%s] = %.2f", kp.id, score
                        )

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
                            knowledge_point_id=(state.get("skill_params") or {}).get("concept_id") or None,
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
