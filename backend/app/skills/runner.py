"""Skill execution — renders Jinja2 prompt templates and calls the LLM.

The runner is async and uses LangChain's ``ainvoke`` for proper streaming
and tool-calling support. It accepts a ``BaseChatModel`` (e.g. ChatOpenAI)
and returns a :class:`SkillResult`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from jinja2 import Template
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from .schema import SkillMeta

__all__ = ["SkillResult", "run_atom", "run_molecule", "run"]

logger = logging.getLogger("edu-agent.skills.runner")


@dataclass
class SkillResult:
    """Structured output returned by every skill execution."""
    output: str = ""
    comprehension: str = ""
    knowledge_delta: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_SYSTEM_PROMPT = (
    "你是一名经验丰富的 K12 学科教师。请根据学生的当前水平和问题，"
    "用清晰、鼓励、循序渐进的方式教学。回答使用中文。"
)


def render_prompt(skill: SkillMeta, state: dict[str, Any]) -> str:
    """Render the skill body as a Jinja2 template against state."""
    if not skill.body.strip():
        return skill.description
    template = Template(skill.body, trim_blocks=True, lstrip_blocks=True)
    return template.render(**state, default="")


async def run_atom(
    skill: SkillMeta,
    state: dict[str, Any],
    llm: BaseChatModel,
    *,
    system_prompt: str | None = None,
) -> SkillResult:
    """Execute an atom skill: render template → call LLM → parse result."""
    prompt = render_prompt(skill, state)
    sys_msg = system_prompt or skill.system_prompt or DEFAULT_SYSTEM_PROMPT

    logger.debug("Running atom skill %r (prompt %d chars)", skill.name, len(prompt))

    messages = [
        SystemMessage(content=sys_msg),
        HumanMessage(content=prompt),
    ]

    response = await llm.ainvoke(messages)
    raw = response.content if hasattr(response, "content") else str(response)

    # Handle list content (some models return multi-part)
    if isinstance(raw, list):
        raw = "".join(
            part if isinstance(part, str) else str(getattr(part, "text", part))
            for part in raw
        )

    return _parse_result(skill, raw, prompt)


async def run_molecule(
    skill: SkillMeta,
    state: dict[str, Any],
    llm: BaseChatModel,
    *,
    system_prompt: str | None = None,
) -> SkillResult:
    """Execute a molecule skill. Currently delegates to run_atom."""
    logger.debug("Running molecule skill %r as atom (subgraph pending)", skill.name)
    return await run_atom(skill, state, llm, system_prompt=system_prompt)


async def run(
    skill: SkillMeta,
    state: dict[str, Any],
    llm: BaseChatModel,
    *,
    system_prompt: str | None = None,
) -> SkillResult:
    """Dispatch to the correct runner based on skill.layer."""
    if skill.layer == "atom":
        return await run_atom(skill, state, llm, system_prompt=system_prompt)
    if skill.layer == "molecule":
        return await run_molecule(skill, state, llm, system_prompt=system_prompt)
    raise NotImplementedError(
        f"Compound skills are handled by the graph compiler, not the runner. Skill: {skill.name}"
    )


# ── internal helpers ──────────────────────────────────────────────


def _parse_result(skill: SkillMeta, raw: str, rendered_prompt: str) -> SkillResult:
    """Best-effort extraction of structured fields from raw LLM output."""
    result = SkillResult(
        metadata={
            "skill_id": skill.name,
            "skill_name": skill.name,
            "prompt_chars": len(rendered_prompt),
        }
    )

    json_payload = _extract_json_block(raw)
    if json_payload is not None:
        result.output = str(json_payload.get("output", raw))
        result.comprehension = str(json_payload.get("comprehension", ""))
        delta = json_payload.get("knowledge_delta")
        if isinstance(delta, dict):
            result.knowledge_delta = delta
    else:
        result.output = raw.strip()
        result.comprehension = "understood"

    return result


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a fenced block or inline JSON."""
    fence_re = re.compile(r"```(?:json)?\s*\n?(?P<json>\{.*?\})\s*```", re.DOTALL)
    match = fence_re.search(text)
    candidates: list[str] = []
    if match:
        candidates.append(match.group("json"))
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
    """Yield candidate {...} substrings for JSON parsing."""
    start = text.find("{")
    if start == -1:
        return []
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
