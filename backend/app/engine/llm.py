"""LLM client factories.

Two clients:
- ``get_llm`` — text teaching model (DeepSeek via OpenAI-compatible endpoint).
- ``get_vision_llm`` — image understanding model (Zhipu GLM-4V-Flash).

Both return fresh instances on each call (cheap, stateless) to avoid
accidental cross-request reuse of streaming buffers.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import settings


def get_llm(model: str | None = None) -> ChatOpenAI:
    """Build a text teaching model client (DeepSeek)."""
    return ChatOpenAI(
        model=model or settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.7,
        streaming=True,
    )


def get_vision_llm() -> ChatOpenAI:
    """Build a vision model client (Zhipu GLM-4V-Flash).

    Used to extract text/content from images the student uploads, so the
    teaching agent (text-only DeepSeek) can reason over the question.
    """
    return ChatOpenAI(
        model=settings.glm_vision_model,
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
        temperature=0.3,
        streaming=False,
        max_tokens=1500,
    )
