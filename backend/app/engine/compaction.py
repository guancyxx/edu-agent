"""Token-budget-driven conversation-history compaction.

When the running message history grows past a configurable fraction of the
model's context window, the middle segment (everything between the FIRST
message and the last ``compress_keep_recent`` messages) is condensed into a
single summary ``SystemMessage``.  The summary preserves the student's topic,
facts, and mistakes so later nodes (router / skills) keep enough context to
stay pedagogically coherent.

Mechanics
---------
``TutorState.messages`` uses LangGraph's ``add_messages`` reducer, which
treats ``RemoveMessage(id=...)`` entries in a node update as deletions.
:func:`maybe_compact` therefore removes both the dropped middle and the recent
window, appends the summary, then re-appends the recent window.  This leaves
the current student message last, where downstream nodes expect it.

Verified reducer behaviour (langgraph 0.6.11): ``add_messages`` auto-assigns
an id to appended messages that lack one, but raises ``ValueError`` when asked
to remove a non-existent id.  Messages that somehow have no ``.id`` (they
should only exist pre-reducer, e.g. hand-built test states) are therefore
silently skipped for removal rather than crashing the chat.

Failure policy: if the LLM summarization call raises, we log a warning and
return ``[]`` — skip this round, retry next round.  Compaction must NEVER
break the conversation.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages import RemoveMessage

from app.config import settings

logger = logging.getLogger("edu-agent.engine.compaction")

# Heuristic chars→tokens coefficient.  Real tokenizers average ~3–4 chars per
# token for English and ~1.5–2 chars per token for Chinese (UTF-8 bytes vs.
# code points differ, but we count code points).  Using a conservative
# coefficient of *fewer* chars per token (i.e. more tokens per char) makes the
# estimator err on the high side, so compaction triggers EARLY rather than
# late — the safe direction for a hard context-window limit.
_CHARS_PER_TOKEN = 2.0

_SUMMARY_SYSTEM_PROMPT = (
    "You are the memory-compaction component of a K12 tutoring system. "
    "Summarize the conversation segment below into a condensed digest that "
    "a teaching agent can use as long-term memory. Preserve, in priority "
    "order: (1) the topics/knowledge points the student has been studying, "
    "(2) concrete facts the student stated (grade, names, numbers, homework "
    "context), (3) the student's mistakes and misconceptions, (4) what help "
    "was already given and whether it worked. Write in the same language as "
    "the conversation. Respond with ONLY the summary text — no preamble, no "
    "markdown headings."
)


def _message_text(message: BaseMessage) -> str:
    """Best-effort plain-text extraction from a message's content."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # multimodal content blocks
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            else:
                text = getattr(part, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content) if content else ""


def estimate_tokens(messages: list[BaseMessage]) -> int:
    """Estimate the total token count of a message list.

    This is a *heuristic* (``ceil(total_chars / 2)`` plus a small per-message
    overhead), not a real tokenizer count.  It is deliberately conservative —
    it prefers to over-estimate so compaction triggers early rather than
    after the real context window has already blown up.
    """
    total_chars = 0
    for message in messages:
        total_chars += len(_message_text(message))
        # per-message overhead (role, separator, id) — ~8 tokens
        total_chars += 16
    return int(total_chars / _CHARS_PER_TOKEN) + len(messages)


def _build_summary_prompt(segment: list[BaseMessage]) -> str:
    """Render the to-be-dropped segment as a transcript for summarization."""
    lines = []
    for message in segment:
        role = getattr(message, "type", None) or "message"
        lines.append(f"[{role}] {_message_text(message)}")
    return (
        "Summarize this tutoring-conversation segment "
        f"({len(segment)} messages, oldest first):\n\n" + "\n".join(lines)
    )


async def _summarize_segment(segment: list[BaseMessage]) -> str:
    """Condense ``segment`` into a single summary string via ONE LLM call."""
    from app.engine.llm import get_llm

    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content=_SUMMARY_SYSTEM_PROMPT),
        HumanMessage(content=_build_summary_prompt(segment)),
    ])
    summary = _message_text(response)
    return summary.strip() or "(empty summary)"


async def maybe_compact(state: dict[str, Any]) -> list:  # noqa: ANN401 — LangGraph state
    """Async entry point: check the token budget, maybe compact the history.

    Returns
    -------
    list
        ``[]`` when the history is under the trigger threshold (or the
        summarization LLM call failed — compaction never breaks the chat),
        otherwise message operations for the ``add_messages`` reducer.
    """
    messages = list(state.get("messages", []) or [])
    if not messages:
        return []

    threshold = settings.context_window_tokens * settings.compress_trigger_ratio
    estimated = estimate_tokens(messages)
    if estimated <= threshold:
        return []
    if len(messages) == 1:
        logger.warning(
            "maybe_compact: compacted history remains over threshold; the single "
            "message is too large to reduce without truncating content"
        )
        return []

    keep_recent = max(1, int(settings.compress_keep_recent))

    async def build(candidate_keep: int) -> tuple[list, list[BaseMessage]]:
        middle = messages[1:-candidate_keep]
        recent = messages[-candidate_keep:]
        summary_text = await _summarize_segment(middle)
        summary = SystemMessage(content=f"[history summary] {summary_text}")

        ops: list = []
        missing_middle = [m for m in middle if not getattr(m, "id", None)]
        recent_removable = all(getattr(m, "id", None) for m in recent)
        for message in middle:
            if getattr(message, "id", None):
                ops.append(RemoveMessage(id=message.id))
        if missing_middle:
            logger.warning(
                "maybe_compact: %d dropped messages had no id — they cannot be "
                "removed via RemoveMessage and will persist in history",
                len(missing_middle),
            )

        if recent_removable:
            ops.extend(RemoveMessage(id=message.id) for message in recent)
            ops.append(summary)
            # add_messages resolves same-id entries against their original
            # positions even if a RemoveMessage for that id appears earlier
            # in the same update.  Clear ids so these are genuinely appended
            # after the summary; the reducer assigns fresh ids.
            ops.extend(message.model_copy(update={"id": None}) for message in recent)
        else:
            logger.warning(
                "maybe_compact: recent window contains messages without id; "
                "falling back to summary-last ordering"
            )
            ops.append(summary)
        return ops, [messages[0], summary, *recent]

    # Segments: [first] + [middle …dropped…] + [last keep_recent].  A
    # too-large configured window is reduced once to guarantee normal-case
    # progress without truncating any individual message.
    keep_recent = min(keep_recent, max(1, len(messages) - 1))
    logger.info(
        "maybe_compact: estimated_tokens=%d > threshold=%d — compacting with %d recent messages",
        estimated, int(threshold), keep_recent,
    )
    try:
        ops, resulting = await build(keep_recent)
        if estimate_tokens(resulting) >= threshold and keep_recent > 1:
            keep_recent = max(1, keep_recent // 2)
            logger.info(
                "maybe_compact: result remains over budget; rebuilding with %d recent messages",
                keep_recent,
            )
            ops, resulting = await build(keep_recent)
    except Exception as exc:
        logger.warning(
            "maybe_compact: summarization failed (%s) — skipping this round", exc
        )
        return []

    if estimate_tokens(resulting) >= threshold:
        logger.warning(
            "maybe_compact: compacted history remains over threshold; a retained "
            "message or summary is too large to reduce without truncating content"
        )
    logger.info(
        "maybe_compact: compacted history into 1 summary SystemMessage with %d recent messages",
        keep_recent,
    )
    return ops
