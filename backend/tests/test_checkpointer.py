"""Tests for the Postgres checkpointer + thread_id selection (audit PR#6 R3).

Covers the new code paths from PR #6:
- ``_normalize_conn_string`` scheme handling in app.engine.checkpointer
- ``_thread_id_for`` owner binding / UUID validation in app.routers.chat
- ``set_graph`` / ``get_graph`` lazy-build semantics in app.routers.chat
"""

from __future__ import annotations

import uuid

import pytest

from app.engine.checkpointer import _normalize_conn_string
from app.routers import chat


# ── _normalize_conn_string ─────────────────────────────────────────


def test_normalize_strips_asyncpg_driver():
    url = "postgresql+asyncpg://user:pass@localhost:5433/edu"
    assert _normalize_conn_string(url) == "postgresql://user:pass@localhost:5433/edu"


def test_normalize_plain_postgresql_passes_through():
    url = "postgresql://user:pass@localhost:5433/edu"
    assert _normalize_conn_string(url) == url


def test_normalize_rejects_sqlite():
    with pytest.raises(ValueError):
        _normalize_conn_string("sqlite:///./edu.db")


def test_normalize_rejects_mysql():
    with pytest.raises(ValueError):
        _normalize_conn_string("mysql://user:pass@localhost:3306/edu")


# ── _thread_id_for ─────────────────────────────────────────────────

USER_ID = "11111111-2222-3333-4444-555555555555"
SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_thread_id_valid_uuid_binds_owner():
    assert chat._thread_id_for(USER_ID, SESSION_ID) == f"chat-{USER_ID}-{SESSION_ID}"


def test_thread_id_binds_different_users_to_different_threads():
    other = "99999999-8888-7777-6666-555555555555"
    assert chat._thread_id_for(USER_ID, SESSION_ID) != chat._thread_id_for(
        other, SESSION_ID
    )


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc",
        "x" * 300,
        "",
        None,
        12345,          # non-string
        ["not", "a", "uuid"],
        {"session": "id"},
    ],
)
def test_thread_id_garbage_returns_none(bad):
    assert chat._thread_id_for(USER_ID, bad) is None


# ── set_graph / get_graph ──────────────────────────────────────────


def test_get_graph_lazily_builds_when_unset():
    chat._tutor_graph = None
    g = chat.get_graph()
    assert g is not None
    assert chat._tutor_graph is g


def test_set_graph_then_get_graph_returns_same_object():
    sentinel = object()
    chat.set_graph(sentinel)
    assert chat.get_graph() is sentinel
    chat._tutor_graph = None  # reset for other tests
