"""Postgres-backed LangGraph checkpointer (replaces MemorySaver in production).

``AsyncPostgresSaver`` persists graph state (messages, iterations, scratch
state) across process restarts, keyed by ``thread_id``.

Design note: the sync ``PostgresSaver`` was considered first, but this app's
graph nodes are async-only (``assess``/``router``/...), so every invocation
goes through the async Pregel loop, which calls the checkpointer's async
methods (``aget_tuple`` etc.).  The sync saver leaves those unimplemented
(``NotImplementedError`` on the first message), hence the async saver.  The
connection context manager is kept in a module-level
:class:`contextlib.AsyncExitStack` so it is closed cleanly on shutdown via
:func:`close_postgres_checkpointer`.
"""
from __future__ import annotations

import contextlib
import logging
from urllib.parse import urlsplit, urlunsplit

from app.config import settings

logger = logging.getLogger("edu-agent.checkpointer")

# Module-level AsyncExitStack holding the AsyncPostgresSaver connection
# context manager.
_stack: contextlib.AsyncExitStack | None = None


def _normalize_conn_string(url: str) -> str:
    """Strip the ``+asyncpg`` driver suffix from the SQLAlchemy DSN.

    ``settings.database_url`` is an async SQLAlchemy URL such as
    ``postgresql+asyncpg://user:pass@host:5432/db``.  The checkpointer
    (psycopg3) wants a plain ``postgresql://`` URL.

    Raises
    ------
    ValueError
        If the scheme is not ``postgresql+asyncpg`` or ``postgresql``.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql+asyncpg", "postgresql"):
        raise ValueError(
            f"Unsupported database scheme for Postgres checkpointer: "
            f"{parts.scheme!r} (expected 'postgresql+asyncpg' or 'postgresql' "
            f"in {settings.database_url!r})"
        )
    scheme = "postgresql"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


async def create_postgres_checkpointer():
    """Create, initialize, and return an ``AsyncPostgresSaver``.

    Runs the idempotent, versioned ``setup()`` DDL (LangGraph checkpoint /
    migrations tables).  Raises on failure — callers should fail fast rather
    than silently degrade to MemorySaver.
    """
    global _stack
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    conn_string = _normalize_conn_string(settings.database_url)
    logger.info("Creating Postgres checkpointer (db=%s)", conn_string.rsplit("@", 1)[-1])

    _stack = contextlib.AsyncExitStack()
    checkpointer = await _stack.enter_async_context(
        AsyncPostgresSaver.from_conn_string(conn_string)
    )
    await checkpointer.setup()
    logger.info("Postgres checkpointer ready (checkpoint tables ensured).")
    return checkpointer


async def close_postgres_checkpointer() -> None:
    """Close the checkpointer connections.  Safe no-op if never created."""
    global _stack
    if _stack is None:
        return
    stack, _stack = _stack, None
    try:
        await stack.aclose()
    except Exception as exc:  # pragma: no cover - shutdown robustness
        logger.warning("Error closing Postgres checkpointer: %s", exc)
