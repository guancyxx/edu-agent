"""Skill execution — renders Jinja2 prompt templates and calls the LLM.

The runner is deliberately decoupled from LangGraph: it accepts a plain
``state`` dict and any callable ``llm`` object. The graph nodes wrap these
functions and feed the resulting :class:`SkillResult` back into state.

Typical usage from a node::

    from app.skills import SkillCatalog, run_atom

    catalog = SkillCatalog(loader.load_directory())
    skill = catalog.get("concept-explain")
    result = run_atom(skill, state, llm)
    state["last_response"] = result.output
    state["knowledge_delta"].update(result.knowledge_delta)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from jinja2 import Template, TemplateError

from .schema import SkillMeta

__all__ = ["SkillResult", "run_atom", "run_molecule", "run", "LLMCallable"]

logger = logging.getLogger(__name__)


class LLMCallable(Protocol):
    """Anything callable as ``llm(prompt: str, **opts) -> str``.

    Works with LangChain ``Runnable.invoke``, plain functions, lambdas, or
    objects implementing ``__call__``.
    """

    def __call__(self, prompt: str, **kwargs: Any) -> str:  # pragma: no cover
        ...


@dataclass
class SkillResult:
    """Structured output returned by every skill execution.

    Attributes:
        output: The main natural-language response shown to the student.
        comprehension: Teacher-side diagnosis — how well the student
            understood the material, used to update the knowledge graph.
            May be empty if the skill did not produce one.
        knowledge_delta: Incremental updates to the student's mastery map.
            Keys are topic ids, values are dicts like
            ``{"mastery": 0.7, "evidence": "..."}``.
        metadata: Extra runtime info (tokens, latency, raw LLM response).
    """

    output: str = ""
    comprehension: str = ""
    knowledge_delta: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# default system prompt
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "你是一名经验丰富的 K12 学科教师。请根据学生的当前水平和问题，"
    "用清晰、鼓励、循序渐进的方式教学。回答使用中文。"
)


# ---------------------------------------------------------------------------
# public execution API
# ---------------------------------------------------------------------------


def render_prompt(skill: SkillMeta, state: dict[str, Any]) -> str:
    """Render the skill body as a Jinja2 template against ``state``.

    Missing variables render as an empty string (via ``default("")``) rather
    than raising, so a skill can reference optional state keys safely.

    Args:
        skill: The skill whose ``.body`` is the template.
        state: Flat dict of student/session variables.
    Returns:
        Rendered prompt string ready to send to the LLM.
    Raises:
        jinja2.TemplateError: If the template is syntactically invalid.
    """
    if not skill.body.strip():
        # Skills without a body act as pure metadata; return the description.
        return skill.description
    template = Template(skill.body, trim_blocks=True, lstrip_blocks=True)
    return template.render(**state, default="")


def run_atom(
    skill: SkillMeta,
    state: dict[str, Any],
    llm: LLMCallable,
    *,
    system_prompt: str | None = None,
    **llm_opts: Any,
) -> SkillResult:
    """Execute an atom skill: render template → call LLM → parse result.

    Args:
        skill: An atom-layer :class:`SkillMeta`.
        state: Student/session state dict (Jinja2 context).
        llm: Callable that takes the rendered prompt and returns a string.
        system_prompt: Override system message; defaults to the skill's own
            ``system_prompt`` or :data:`DEFAULT_SYSTEM_PROMPT`.
        **llm_opts: Extra kwargs forwarded to ``llm()`` (e.g. ``temperature``).
    Returns:
        :class:`SkillResult` with the LLM's response.
    """
    prompt = render_prompt(skill, state)
    sys_msg = system_prompt or skill.system_prompt or DEFAULT_SYSTEM_PROMPT
    full_prompt = f"[system]\n{sys_msg}\n\n[user]\n{prompt}"

    logger.debug("Running atom skill %r (prompt %d chars)", skill.id, len(full_prompt))
    raw = _invoke_llm(llm, full_prompt, **llm_opts)
    return _parse_result(skill, raw, prompt)


def run_molecule(
    skill: SkillMeta,
    state: dict[str, Any],
    llm: LLMCallable,
    *,
    system_prompt: str | None = None,
    **llm_opts: Any,
) -> SkillResult:
    """Execute a molecule skill.

    Currently delegates to :func:`run_atom` (single LLM call). The real
    subgraph orchestration — walking ``skill.steps`` / ``skill.deps`` and
    composing multiple atom results — will be wired in once the LangGraph
    subgraph integration is available. This stub keeps the interface stable.

    Args:
        skill: A molecule-layer :class:`SkillMeta`.
        state: Student/session state dict.
        llm: Callable LLM interface.
        system_prompt: Optional system-message override.
        **llm_opts: Forwarded to the LLM.
    Returns:
        :class:`SkillResult` (currently identical to ``run_atom`` output).
    """
    logger.debug(
        "Running molecule skill %r as atom (subgraph integration pending)",
        skill.id,
    )
    return run_atom(skill, state, llm, system_prompt=system_prompt, **llm_opts)


def run(
    skill: SkillMeta,
    state: dict[str, Any],
    llm: LLMCallable,
    *,
    system_prompt: str | None = None,
    **llm_opts: Any,
) -> SkillResult:
    """Dispatch to the correct runner based on ``skill.layer``.

    This is the single entry point graph nodes should call. Compounds are
    not yet supported at runtime (they describe session-level YAML configs
    handled by the graph compiler).

    Args:
        skill: Any :class:`SkillMeta`.
        state: Student/session state dict.
        llm: Callable LLM interface.
        system_prompt: Optional system-message override.
        **llm_opts: Forwarded to the LLM.
    Returns:
        :class:`SkillResult`.
    Raises:
        NotImplementedError: If ``skill.layer == "compound"``.
    """
    if skill.layer == "atom":
        return run_atom(skill, state, llm, system_prompt=system_prompt, **llm_opts)
    if skill.layer == "molecule":
        return run_molecule(skill, state, llm, system_prompt=system_prompt, **llm_opts)
    raise NotImplementedError(
        f"Runtime execution of compound skills is handled by the graph "
        f"compiler, not the runner. Skill: {skill.id}"
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _invoke_llm(llm: LLMCallable, prompt: str, **opts: Any) -> str:
    """Call ``llm`` and normalise the return value to ``str``.

    Handles three common shapes:
    - plain ``str``
    - objects with ``.content`` (LangChain ``AIMessage``)
    - dicts with a ``"content"`` key
    """
    result = llm(prompt, **opts)
    if isinstance(result, str):
        return result
    # LangChain AIMessage / BaseMessage
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # multi-part content
        return "".join(
            part if isinstance(part, str) else str(getattr(part, "text", part))
            for part in content
        )
    if isinstance(result, dict) and "content" in result:
        return str(result["content"])
    return str(result)


def _parse_result(
    skill: SkillMeta, raw: str, rendered_prompt: str
) -> SkillResult:
    """Best-effort extraction of structured fields from raw LLM output.

    If the LLM returns a fenced JSON block (```` ```json ... ``` ````), we
    try to parse ``output`` / ``comprehension`` / ``knowledge_delta`` from
    it. Otherwise the full text becomes ``output`` and the other fields are
    left empty for the graph to fill via the observer node.
    """
    result = SkillResult(
        metadata={
            "skill_id": skill.id,
            "skill_name": skill.name,
            "prompt_chars": len(rendered_prompt),
            "raw": raw,
        }
    )

    # Look for a ```json fenced block or a leading {...} object.
    json_payload = _extract_json_block(raw)
    if json_payload is not None:
        result.output = str(json_payload.get("output", raw))
        result.comprehension = str(json_payload.get("comprehension", ""))
        delta = json_payload.get("knowledge_delta")
        if isinstance(delta, dict):
            result.knowledge_delta = delta
    else:
        result.output = raw.strip()

    return result


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a fenced block or inline JSON.

    Returns ``None`` if no valid JSON object is found.
    """
    # Fenced ```json ... ``` block
    import re

    fence_re = re.compile(r"```(?:json)?\s*\n?(?P<json>\{.*?\})\s*```", re.DOTALL)
    match = fence_re.search(text)
    candidates: list[str] = []
    if match:
        candidates.append(match.group("json"))
    # Inline bare object at start/end
    candidates.extend(_find_inline_json(text))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _find_inline_json(text: str) -> list[str]:
    """Yield candidate ``{...}`` substrings for JSON parsing."""
    start = text.find("{")
    if start == -1:
        return []
    # Walk forward balancing braces.
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return [text[start : i + 1]]
    return []
