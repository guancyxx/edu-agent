"""LLM client factory.

Centralises ChatOpenAI construction so every node / skill uses the same model
configuration (DeepSeek via an OpenAI-compatible endpoint). Returns a fresh
instance on each call — instances are cheap and stateless aside from the
config, so this avoids accidental cross-request reuse of streaming buffers.
"""

from langchain_openai import ChatOpenAI

from app.config import settings


def get_llm() -> ChatOpenAI:
    """Build and return a configured ``ChatOpenAI`` client.

    Reads connection details from :data:`app.config.settings` so secrets and
    endpoints stay in one place (environment / ``.env``).

    Returns
    -------
    ChatOpenAI
        A streaming-enabled client pointed at the configured DeepSeek endpoint.
    """
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.7,
        streaming=True,
    )
