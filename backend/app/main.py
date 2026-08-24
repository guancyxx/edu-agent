import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import health, chat, auth, mistakes

logger = logging.getLogger("edu-agent")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("EduAgent API starting up...")
    # Create database tables on first run
    try:
        from app.database import engine
        from app.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured.")
    except Exception as e:
        logger.warning("Could not create database tables: %s (DB not ready?)", e)

    # Postgres-backed LangGraph checkpointer (AsyncPostgresSaver — the app's
    # graph nodes are async-only).  Failure is fatal on purpose: losing
    # chat-thread persistence is not something we degrade silently to
    # MemorySaver for.
    from app.engine.checkpointer import (
        create_postgres_checkpointer,
        close_postgres_checkpointer,
    )
    from app.engine.graph import build_tutor_graph
    from app.routers import chat

    try:
        cp = await create_postgres_checkpointer()
        app_graph = build_tutor_graph(checkpointer=cp)
        chat.set_graph(app_graph)
        logger.info("Tutor graph compiled with Postgres checkpointer.")
    except Exception as e:
        logger.error(
            "Failed to initialize Postgres checkpointer — check "
            "settings.database_url / Postgres availability: %s", e,
        )
        raise

    yield
    logger.info("EduAgent API shutting down...")
    await close_postgres_checkpointer()


app = FastAPI(
    title="EduAgent API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(mistakes.router)
