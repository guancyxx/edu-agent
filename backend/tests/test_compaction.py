"""Tests for token-budget-driven conversation-history compaction (R2).

Covers:
- ``estimate_tokens`` heuristic sanity (monotonic, non-zero, conservative)
- ``maybe_compact`` under-threshold no-op / over-threshold compaction /
  LLM-failure graceful skip / first+recent window preservation
- assess_node message-ops flowing through the ``add_messages`` reducer in a
  minimal in-memory StateGraph with MemorySaver
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)

from app.engine import compaction
from app.engine.compaction import estimate_tokens, maybe_compact
from app.config import settings


def _mk_messages(n: int, chars: int = 50, with_ids: bool = True) -> list:
    """Build an alternating Human/AI conversation of ``n`` messages."""
    msgs = []
    for i in range(n):
        cls = HumanMessage if i % 2 == 0 else AIMessage
        kwargs = {"id": f"m{i}"} if with_ids else {}
        msgs.append(cls(content=f"message {i} " + "x" * chars, **kwargs))
    return msgs


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if hasattr(asyncio, "get_event_loop") else asyncio.run(coro)


class _StubLLM:
    """Stub LLM whose ainvoke returns a canned summary AIMessage."""

    def __init__(self, reply: str = "学生正在学习一元一次方程，曾在移项时出错。"):
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(content=self.reply)


class _ExplodingLLM:
    async def ainvoke(self, messages):
        raise RuntimeError("LLM is down")


def _patch_settings(**overrides):
    """Context-manager-free helper: patch settings fields, restore after test."""
    original = {k: getattr(settings, k) for k in overrides}
    for k, v in overrides.items():
        setattr(settings, k, v)
    return original


@pytest.fixture(autouse=True)
def restore_settings():
    """Snapshot compaction settings so tests can patch them freely."""
    keys = ("context_window_tokens", "compress_trigger_ratio", "compress_keep_recent")
    snapshot = {k: getattr(settings, k) for k in keys}
    yield
    for k, v in snapshot.items():
        setattr(settings, k, v)


def _stub_get_llm(stub):
    def _fake_get_llm(model=None):
        return stub
    return _fake_get_llm


# ── estimate_tokens ────────────────────────────────────────────────


def test_estimate_tokens_positive_for_empty_and_nonempty():
    assert estimate_tokens([]) == 0
    assert estimate_tokens(_mk_messages(3)) > 0


def test_estimate_tokens_monotonic():
    msgs = _mk_messages(12)
    prev = 0
    for i in range(1, len(msgs) + 1):
        current = estimate_tokens(msgs[:i])
        assert current >= prev, f"estimate decreased at prefix {i}"
        prev = current


def test_estimate_tokens_conservative_for_chinese():
    # Chinese text: ~1.5-2 chars/token realistically; our coefficient of 2
    # chars/token must not UNDER-estimate. 100 Chinese chars should count
    # as at least 50 tokens.
    msg = HumanMessage(content="数" * 100, id="c1")
    assert estimate_tokens([msg]) >= 50


def test_estimate_tokens_handles_multimodal_content():
    msg = HumanMessage(content=[{"type": "text", "text": "hello world"}], id="mm1")
    # Should not raise; text part contributes.
    assert estimate_tokens([msg]) > 0


# ── maybe_compact ──────────────────────────────────────────────────


def test_under_threshold_noop(monkeypatch):
    monkeypatch.setattr(settings, "context_window_tokens", 1_000_000)
    stub = _StubLLM()
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(stub))
    ops = _run(maybe_compact({"messages": _mk_messages(20)}))
    assert ops == []
    assert stub.calls == 0


def test_over_threshold_compacts(monkeypatch):
    monkeypatch.setattr(settings, "context_window_tokens", 1_000)
    monkeypatch.setattr(settings, "compress_trigger_ratio", 0.5)
    monkeypatch.setattr(settings, "compress_keep_recent", 4)
    stub = _StubLLM()
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(stub))

    msgs = _mk_messages(20, chars=80)  # well over 500 estimated tokens
    ops = _run(maybe_compact({"messages": msgs}))

    removals = [op for op in ops if isinstance(op, RemoveMessage)]
    summaries = [op for op in ops if isinstance(op, SystemMessage)]
    assert len(removals) == 15  # 20 - first(1) - recent(4)
    assert {r.id for r in removals} == {f"m{i}" for i in range(1, 16)}
    assert len(summaries) == 1
    assert stub.calls == 1  # exactly ONE LLM call


def test_over_threshold_keeps_first_and_recent_ids(monkeypatch):
    monkeypatch.setattr(settings, "context_window_tokens", 1_000)
    monkeypatch.setattr(settings, "compress_trigger_ratio", 0.5)
    monkeypatch.setattr(settings, "compress_keep_recent", 6)
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(_StubLLM()))

    msgs = _mk_messages(20)
    ops = _run(maybe_compact({"messages": msgs}))
    removed_ids = {r.id for r in ops if isinstance(r, RemoveMessage)}
    assert "m0" not in removed_ids  # first message kept
    for i in range(14, 20):  # last 6 kept
        assert f"m{i}" not in removed_ids


def test_llm_failure_returns_empty(monkeypatch, caplog):
    monkeypatch.setattr(settings, "context_window_tokens", 1_000)
    monkeypatch.setattr(settings, "compress_trigger_ratio", 0.5)
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(_ExplodingLLM()))
    ops = _run(maybe_compact({"messages": _mk_messages(20, chars=80)}))
    assert ops == []  # graceful skip — never break the chat


def test_small_history_noop(monkeypatch):
    # History no longer than first + keep_recent: nothing droppable.
    monkeypatch.setattr(settings, "context_window_tokens", 1)
    monkeypatch.setattr(settings, "compress_trigger_ratio", 1.0)
    monkeypatch.setattr(settings, "compress_keep_recent", 6)
    stub = _StubLLM()
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(stub))
    ops = _run(maybe_compact({"messages": _mk_messages(7)}))
    assert ops == []
    assert stub.calls == 0


def test_empty_history_noop(monkeypatch):
    monkeypatch.setattr(settings, "context_window_tokens", 1)
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(_StubLLM()))
    assert _run(maybe_compact({"messages": []})) == []


def test_messages_without_id_skipped_for_removal(monkeypatch):
    # Messages lacking .id can't be RemoveMessage'd — no crash, no removal op.
    monkeypatch.setattr(settings, "context_window_tokens", 1_000)
    monkeypatch.setattr(settings, "compress_trigger_ratio", 0.5)
    monkeypatch.setattr(settings, "compress_keep_recent", 2)
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(_StubLLM()))
    msgs = _mk_messages(10, chars=80, with_ids=False)
    ops = _run(maybe_compact({"messages": msgs}))
    removals = [op for op in ops if isinstance(op, RemoveMessage)]
    assert removals == []  # no ids → no RemoveMessage ops emitted
    assert any(isinstance(op, SystemMessage) for op in ops)


# ── add_messages reducer integration ───────────────────────────────


def test_reducer_applies_removals_and_summary(monkeypatch):
    from langgraph.graph.message import add_messages

    monkeypatch.setattr(settings, "context_window_tokens", 1_000)
    monkeypatch.setattr(settings, "compress_trigger_ratio", 0.5)
    monkeypatch.setattr(settings, "compress_keep_recent", 4)
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(_StubLLM()))

    msgs = _mk_messages(20, chars=80)
    # Pre-existing history already has ids (as it would in the checkpointer).
    ops = _run(maybe_compact({"messages": msgs}))
    new_history = add_messages(msgs, ops)

    ids = [m.id for m in new_history]
    assert ids[0] == "m0"  # first survives
    assert set(ids[1:5]) == {"m16", "m17", "m18", "m19"}  # recent window survives
    assert isinstance(new_history[-1], SystemMessage)  # summary appended last
    assert "m5" not in ids  # middle dropped


def test_assess_node_ops_flow_through_graph(monkeypatch):
    """Minimal in-memory graph: assess-like node returns compaction ops and
    the add_messages reducer applies them to checkpointed state."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.checkpoint.memory import MemorySaver

    monkeypatch.setattr(settings, "context_window_tokens", 1_000)
    monkeypatch.setattr(settings, "compress_trigger_ratio", 0.5)
    monkeypatch.setattr(settings, "compress_keep_recent", 4)
    monkeypatch.setattr("app.engine.llm.get_llm", _stub_get_llm(_StubLLM()))

    async def fake_assess(state):
        # Mirrors assess_node's compaction block exactly.
        update: dict[str, Any] = {"iteration_count": 1}
        ops = await maybe_compact(state)
        if ops:
            update["messages"] = ops
        return update

    async def sink(state):
        return {}

    graph = StateGraph(dict)
    # Use TutorState-like annotation via the real state module.
    from app.engine.state import TutorState
    graph = StateGraph(TutorState)
    graph.add_node("assess", fake_assess)
    graph.add_node("sink", sink)
    graph.add_edge(START, "assess")
    graph.add_edge("assess", "sink")
    graph.add_edge("sink", END)
    app = graph.compile(checkpointer=MemorySaver())

    history = _mk_messages(20, chars=80)
    result = _run(app.ainvoke(
        {"messages": history},
        config={"configurable": {"thread_id": "t-compaction"}},
    ))
    final = result["messages"]
    ids = [m.id for m in final]
    assert ids[0] == "m0"
    assert set(ids[1:5]) == {"m16", "m17", "m18", "m19"}
    assert "m5" not in ids
    assert isinstance(final[-1], SystemMessage) and "summary" in final[-1].content
