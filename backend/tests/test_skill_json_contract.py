"""A4 batch-1: skill templates emit the single-JSON contract the runner parses.

Tests render each template against realistic state and assert the rendered
prompt instructs the exact JSON shape; plus an end-to-end _parse_result pass
with a compliant sample reply. No LLM calls.
"""

from __future__ import annotations

import json

from app.engine import nodes
from app.skills.loader import SkillLoader
from app.skills.runner import _parse_result, render_prompt
from langchain_core.messages import HumanMessage

KP_MENU = [
    {"id": "7-1-3", "title": "有理数的加减法", "difficulty": 2, "description": "...", "prerequisites": ["7-1-2"]},
    {"id": "7-1-4", "title": "有理数的乘除法", "difficulty": 2, "description": "...", "prerequisites": ["7-1-3"]},
]


def _render(name: str, state: dict) -> str:
    loader = SkillLoader()
    skills = loader.load_directory("../skills")
    by_name = {s.name: s for s in skills}
    return render_prompt(by_name[name], state)


def test_concept_explain_prompt_contains_contract():
    prompt = _render("concept-explain", {
        "student_message": "我不懂有理数加减",
        "concept_id": "7-1-3",
        "subject": "math", "grade": 7, "ability_level": "beginner",
        "emotion_state": {}, "curriculum_kps": KP_MENU,
    })
    assert '"output"' in prompt and '"comprehension"' in prompt and '"knowledge_delta"' in prompt
    assert "```json" in prompt
    assert "`7-1-3`" in prompt  # curriculum menu rendered
    assert "{{ concept_id }}" not in prompt  # resolved, not raw
    assert "7-1-3" in prompt


def test_knowledge_check_prompt_contains_contract():
    prompt = _render("knowledge-check", {
        "student_message": "考考我",
        "concept_id": "7-1-3",
        "subject": "math", "grade": 7, "ability_level": "beginner",
        "curriculum_kps": KP_MENU, "previous_output": "讲解内容",
    })
    assert '"output"' in prompt and '"comprehension"' in prompt and '"knowledge_delta"' in prompt
    assert '"comprehension": "understood"' in prompt
    assert '"knowledge_delta": {}' in prompt


def test_runner_parses_compliant_reply():
    inner_md = "## 有理数加减\n\n**核心**：同号相加...\n\n$$(-3)+(-2)=-5$$"
    reply = "```json\n" + json.dumps({
        "output": inner_md,
        "comprehension": "confused",
        "knowledge_delta": {"7-1-3": 0.35},
    }, ensure_ascii=False) + "\n```"
    loader = SkillLoader()
    skills = loader.load_directory("../skills")
    meta = {s.name: s for s in skills}["concept-explain"]
    result = _parse_result(meta, reply, "prompt")
    assert result.output == inner_md
    assert result.comprehension == "confused"
    assert result.knowledge_delta == {"7-1-3": 0.35}


def test_runner_degrades_gracefully_on_plain_markdown():
    reply = "## 普通讲解\n没有 JSON 的旧式回复"
    loader = SkillLoader()
    skills = loader.load_directory("../skills")
    meta = {s.name: s for s in skills}["concept-explain"]
    result = _parse_result(meta, reply, "prompt")
    assert result.output == reply.strip()
    assert result.comprehension == "understood"
    assert result.knowledge_delta == {}


def test_contract_survives_empty_curriculum():
    prompt = _render("concept-explain", {
        "student_message": "你好",
        "concept_id": "",
        "subject": "math", "grade": 7, "ability_level": "beginner",
        "emotion_state": {}, "curriculum_kps": [],
    })
    assert '"knowledge_delta"' in prompt  # contract instructions survive empty menu
    assert "## Curriculum Knowledge Points" not in prompt  # menu section hidden


async def test_router_bumps_iteration_count():
    state = {
        "messages": [HumanMessage(content="画个图讲讲负数")],
        "emotion_state": {},
    }
    out = await nodes.router_node(state)
    assert out["selected_skill"] == "picture-explain"
    assert out["iteration_count"] == 1


async def test_confused_loop_terminates_at_max_iterations():
    from app.engine.nodes import observe_node
    state = {
        "messages": [HumanMessage(content="还是不懂")],
        "comprehension_signal": "confused",
        "iteration_count": 3,
    }
    out = await observe_node(state)
    assert out["should_continue"] is False


async def test_confused_continues_below_max_iterations():
    from app.engine.nodes import observe_node
    state = {
        "messages": [HumanMessage(content="还是不懂")],
        "comprehension_signal": "confused",
        "iteration_count": 2,
    }
    out = await observe_node(state)
    assert out["should_continue"] is True
