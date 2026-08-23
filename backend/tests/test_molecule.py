"""Tests for the molecule → LangGraph subgraph expansion (A2)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List

import pytest

from app.skills.loader import SkillLoader
from app.skills.molecule import run_molecule
from app.skills.runner import render_prompt
from app.skills.schema import SkillMeta

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

_state = {
    "subject": "math",
    "grade": 7,
    "ability_level": "beginner",
    "student_message": "这道题不会：3x + 5 = 20 怎么解？",
    "problem_context": "3x + 5 = 20",
    "concept_id": "一元一次方程",
    "emotion_state": {},
    "knowledge_mastery": {},
    "recent_mistakes": [],
    "skill_params": {},
}


class StubLLM:
    """Records every ainvoke and returns a canned, distinguishable reply."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: List[Any] = []
        self.fail_on = fail_on

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        from langchain_core.messages import AIMessage

        self.calls.append(messages)
        idx = len(self.calls) - 1
        marker = f"MARKER-STEP-{idx + 1}"
        return AIMessage(content=f"这是第 {idx + 1} 步的回复 {marker}")


def _load_skills() -> Any:
    loader = SkillLoader(project_root=Path(__file__).resolve().parents[2])
    return {s.id: s for s in loader.load_directory()}


def _resolver(skills: Any):
    return lambda name: skills.get(name)


async def test_three_steps_in_order() -> None:
    skills = _load_skills()
    guided = skills["guided-solve"]
    llm = StubLLM()

    result = await run_molecule(guided, dict(_state), llm, resolver=_resolver(skills))

    assert len(llm.calls) == 3, f"expected 3 LLM calls, got {len(llm.calls)}"
    order = [s["skill"] for s in result.metadata["steps"]]
    assert order == ["hint-generate", "concept-explain", "knowledge-check"]
    assert "第 1 步 · 分级提示" in result.output
    assert "第 2 步 · 概念讲解" in result.output
    assert "第 3 步 · 理解检测" in result.output
    assert result.metadata["fallback"] is False


async def test_previous_output_chaining() -> None:
    skills = _load_skills()
    guided = skills["guided-solve"]
    llm = StubLLM()

    await run_molecule(guided, dict(_state), llm, resolver=_resolver(skills))

    prompts = [msgs[-1].content for msgs in llm.calls]
    # Chaining is context-injection + per-template opt-in (D2): only templates
    # that reference {{ previous_output }} surface the prior step's reply.
    # hint-generate (1st) and concept-explain (2nd) don't reference it by
    # design — knowledge-check (3rd) does, and its anchor is the immediately
    # preceding step (concept-explain = MARKER-STEP-2).
    assert "MARKER-STEP-1" not in prompts[0]
    assert "MARKER-STEP-1" not in prompts[1]
    assert "MARKER-STEP-2" in prompts[2]


async def test_molecule_body_used_as_system_prompt() -> None:
    skills = _load_skills()
    guided = skills["guided-solve"]
    llm = StubLLM()

    await run_molecule(guided, dict(_state), llm, resolver=_resolver(skills))

    for msgs in llm.calls:
        system = msgs[0].content
        assert "Socratic tutor" in system, "molecule body should be the system prompt"
        assert "3x + 5 = 20" in system, "body context should render the problem"


async def test_empty_steps_falls_back() -> None:
    skills = _load_skills()
    skeleton = SkillMeta(
        name="empty-mol",
        layer="molecule",
        category="core",
        description="molecule with no steps",
        steps=[],
        body="You are a Socratic tutor.",
    )
    llm = StubLLM()

    result = await run_molecule(skeleton, dict(_state), llm, resolver=_resolver(skills))

    assert len(llm.calls) == 1
    assert result.metadata["fallback"] is True


async def test_missing_step_skipped() -> None:
    skills = _load_skills()
    skeleton = SkillMeta(
        name="partial-mol",
        layer="molecule",
        category="core",
        description="molecule with one unknown step",
        steps=["hint-generate", "no-such-atom"],
        body="You are a Socratic tutor.",
    )
    llm = StubLLM()

    result = await run_molecule(skeleton, dict(_state), llm, resolver=_resolver(skills))

    assert len(llm.calls) == 1
    assert [s["skill"] for s in result.metadata["steps"]] == ["hint-generate"]


def test_knowledge_check_template_renders() -> None:
    skills = _load_skills()
    check = skills["knowledge-check"]
    rendered = render_prompt(
        check,
        {
            "concept_id": "一元一次方程",
            "subject": "math",
            "grade": 7,
            "ability_level": "beginner",
            "previous_output": "X-ANCHOR-CONTENT",
        },
    )
    assert "X-ANCHOR-CONTENT" in rendered


def test_knowledge_check_template_without_previous() -> None:
    skills = _load_skills()
    check = skills["knowledge-check"]
    rendered = render_prompt(
        check,
        {
            "concept_id": "一元一次方程",
            "subject": "math",
            "grade": 7,
            "ability_level": "beginner",
        },
    )
    assert "刚讲过的内容" not in rendered
