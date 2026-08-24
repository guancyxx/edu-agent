"""Session history endpoint tests (PR: session history load).

Covers: ownership check (404 for other users' / unknown sessions),
invalid UUID (400), snapshot→history mapping (human/ai/system roles,
multimodal content flattening, skipped non-conversational types), and
the empty-history path (session exists but no checkpoint → []).
LLM and checkpointer seams are monkeypatched — no network, no DB.
"""

import uuid as uuid_mod
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

import app.routers.chat as chat
from app.models import ChatSessionDB, User


def _user() -> User:
    return User(id=uuid_mod.uuid4(), username="stu", password_hash="x")


def _session(user_id) -> ChatSessionDB:
    return ChatSessionDB(id=uuid_mod.uuid4(), user_id=user_id, subject="math")


class FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeDB:
    """Minimal AsyncSession double: returns a canned ChatSessionDB."""

    def __init__(self, obj):
        self._obj = obj

    async def execute(self, *_a, **_k):
        return FakeResult(self._obj)


@pytest.fixture
def graph_spy(monkeypatch):
    """Replace get_graph() with a spy we can point at any snapshot."""
    holder = SimpleNamespace(snapshot=None, called_with=None)

    class FakeGraph:
        async def aget_state(self, config):
            holder.called_with = config
            return holder.snapshot

    monkeypatch.setattr(chat, "get_graph", lambda: FakeGraph())
    return holder


async def test_history_maps_roles_and_skips_non_conversational(graph_spy):
    snapshot = SimpleNamespace(values={"messages": [
        HumanMessage(content="  什么是负数  "),
        AIMessage(content="负数是小于0的数"),
        SystemMessage(content="摘要：学生在学负数"),
        ToolMessage(content="internal", tool_call_id="t1"),
    ]})
    out = chat._history_from_snapshot(snapshot)
    assert [(m.role, m.content) for m in out] == [
        ("user", "什么是负数"),
        ("assistant", "负数是小于0的数"),
        ("summary", "摘要：学生在学负数"),
    ]


async def test_history_flattens_multimodal_content(graph_spy):
    snapshot = SimpleNamespace(values={"messages": [
        HumanMessage(content=[
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:..."}},
            {"type": "text", "text": "第二段"},
        ]),
    ]})
    out = chat._history_from_snapshot(snapshot)
    assert out == [chat.HistoryMessage(role="user", content="看图第二段")]


async def test_history_empty_for_missing_snapshot(graph_spy):
    assert chat._history_from_snapshot(None) == []
    # session exists but never checkpointed → aget_state returns None
    assert chat._history_from_snapshot(SimpleNamespace(values={})) == []


async def test_endpoint_returns_mapped_history(graph_spy, monkeypatch):
    user = _user()
    s = _session(user.id)
    graph_spy.snapshot = SimpleNamespace(values={"messages": [
        HumanMessage(content="问题"), AIMessage(content="回答"),
    ]})

    out = await chat.get_session_messages(str(s.id), user, FakeDB(s))
    assert [(m.role, m.content) for m in out] == [
        ("user", "问题"), ("assistant", "回答"),
    ]
    # thread must be bound to the OWNER (audit PR#6 R1 pattern)
    assert graph_spy.called_with["configurable"]["thread_id"] == f"chat-{user.id}-{s.id}"


async def test_endpoint_404_for_foreign_or_unknown_session(graph_spy):
    user = _user()
    other_session = _session(uuid_mod.uuid4())  # belongs to someone else

    # ownership query finds nothing (correct behavior: WHERE user_id mismatch)
    with pytest.raises(HTTPException) as ei:
        await chat.get_session_messages(str(other_session.id), user, FakeDB(None))
    assert ei.value.status_code == 404


async def test_endpoint_400_for_invalid_uuid(graph_spy):
    with pytest.raises(HTTPException) as ei:
        await chat.get_session_messages("not-a-uuid", _user(), FakeDB(None))
    assert ei.value.status_code == 400


async def test_endpoint_503_when_checkpointer_fails(graph_spy, monkeypatch):
    user = _user()
    s = _session(user.id)

    class BrokenGraph:
        async def aget_state(self, config):
            raise RuntimeError("db down")

    monkeypatch.setattr(chat, "get_graph", lambda: BrokenGraph())
    with pytest.raises(HTTPException) as ei:
        await chat.get_session_messages(str(s.id), user, FakeDB(s))
    assert ei.value.status_code == 503
