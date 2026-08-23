"""Tests for router_node short-circuit ordering (visual before emotion).

Covers the audit note from PR #3: a student with confusion > 0.8 who explicitly
asks for a picture must land on picture-explain, not emotion-respond.
"""

from __future__ import annotations

from typing import Any

import pytest

from langchain_core.messages import HumanMessage

from app.engine.nodes import router_node
from app.engine.state import TutorState


def _state(message: Any, emotion: dict[str, float] | None = None) -> TutorState:
    """Minimal TutorState slice accepted by router_node's short-circuits."""
    msgs = message if isinstance(message, list) else [HumanMessage(content=message)]
    state: TutorState = {
        "messages": msgs,  # type: ignore[typeddict-item]
        "emotion_state": emotion or {},
        "subject": "math",
        "grade": 7,
        "ability_level": "average",
    }
    return state


@pytest.mark.asyncio
async def test_visual_request_wins_over_high_frustration():
    """Explicit picture request + frustration 0.9 → picture-explain (not emotion-respond)."""
    state = _state(
        "什么是负数？画个图讲讲",
        emotion={"frustration": 0.9, "confusion": 0.85},
    )
    out = await router_node(state)
    assert out["selected_skill"] == "picture-explain"


@pytest.mark.asyncio
async def test_emotion_gate_still_fires_without_visual_keyword():
    """High frustration, plain message → emotion-respond (ordering change must not break this)."""
    state = _state(
        "我还是不懂，太难了",
        emotion={"frustration": 0.9, "confusion": 0.85},
    )
    out = await router_node(state)
    assert out["selected_skill"] == "emotion-respond"


@pytest.mark.asyncio
async def test_visual_keyword_variants_all_short_circuit():
    """Every documented keyword routes to picture-explain regardless of emotion."""
    for kw in ("画个图", "画图讲讲", "图解一下", "看图讲", "用图说明", "eli5", "ELI5"):
        state = _state(f"{kw}，负数是什么", emotion={"frustration": 0.95, "confusion": 0.9})
        out = await router_node(state)
        assert out["selected_skill"] == "picture-explain", f"keyword {kw!r} failed"


@pytest.mark.asyncio
async def test_calm_student_visual_request_also_short_circuits():
    """No emotion at all — visual request still deterministic (pre-existing behavior)."""
    state = _state("勾股定理解释下，图解")
    out = await router_node(state)
    assert out["selected_skill"] == "picture-explain"


@pytest.mark.asyncio
async def test_list_content_message_form_supported():
    """Multimodal list content (image + text parts) still detected for keywords."""
    state = _state(
        [{"type": "text", "text": "帮我画个图讲讲这道题"}],
        emotion={"confusion": 0.95},
    )
    out = await router_node(state)
    assert out["selected_skill"] == "picture-explain"
