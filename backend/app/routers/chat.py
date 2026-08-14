"""Chat router — HTTP and WebSocket endpoints for tutoring conversations.

WebSocket supports JWT auth via query param: ws://host/api/chat/ws?token=eyJ...
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.engine.graph import build_tutor_graph
from app.models import User, TeachingEventDB
from app.profile.store import profile_store
from app.skills.loader import SkillLoader
from app.skills.catalog import SkillCatalog
from app.utils.auth import decode_access_token

logger = logging.getLogger("edu-agent.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ── Shared singletons ──────────────────────────────────────────────

_skill_loader = SkillLoader()
_loaded_skills = _skill_loader.load_directory("../skills")
_catalog = SkillCatalog(_loaded_skills)
_tutor_graph = build_tutor_graph()


async def _extract_text_from_images(
    images: list[str],
    message: str = "",
) -> str:
    """Extract question/content text from images via the vision model.

    Uses the Zhipu GLM vision model to "read" the image (math problem,
    geometry diagram, handwritten formula, etc.) and return a text
    description that the text-only teaching model can reason over.
    """
    from app.engine.llm import get_vision_llm

    vision_llm = get_vision_llm()

    content_parts: list[dict] = []
    for img in images[:4]:
        content_parts.append({"type": "image_url", "image_url": {"url": img}})
    instruction = (
        "这是一道题目或学习内容的图片。请准确读出图中的题目文字、公式、"
        "图形信息。如果是数学题，请用文字描述题目和已知条件；如果是几何图，"
        "请描述图形的形状、标注和关系。只输出识别到的内容，不要解答。"
    )
    if message.strip():
        instruction += f"\n\n学生的问题：{message}"
    content_parts.append({"type": "text", "text": instruction})

    try:
        response = await vision_llm.ainvoke([
            HumanMessage(content=content_parts)
        ])
        extracted = response.content if hasattr(response, "content") else str(response)
        if isinstance(extracted, list):
            extracted = "".join(
                part if isinstance(part, str) else str(getattr(part, "text", part))
                for part in extracted
            )
        return extracted.strip()
    except Exception as e:
        logger.warning("Vision extraction failed (%s)", e)
        return ""


# ── Token extraction for WebSocket ─────────────────────────────────

async def _get_user_from_ws_token(websocket: WebSocket, db: AsyncSession) -> Optional[User]:
    """Extract JWT from query param ?token=... and return the User or None."""
    token = websocket.query_params.get("token")
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    return result.scalar_one_or_none()


# ── HTTP Models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    subject: str = "math"


class ChatResponse(BaseModel):
    reply: str
    skill_used: str
    comprehension: str
    iteration_count: int


# ── HTTP Endpoint (requires auth) ──────────────────────────────────

@router.post("/send", response_model=ChatResponse)
async def send_message(
    req: ChatRequest,
    user: User = Depends(
        __import__("app.routers.auth", fromlist=["get_current_user"]).get_current_user
    ),
):
    """Non-streaming chat endpoint."""
    # Load student profile
    async with async_session() as db:
        profile = await profile_store.load(db, str(user.id))

    state_dict = profile.to_state_dict()
    state_dict["subject"] = req.subject
    state_dict["role"] = user.role
    state_dict["iteration_count"] = 0

    result = await _tutor_graph.ainvoke(
        {"messages": [HumanMessage(content=req.message)], **state_dict},
        config={"configurable": {"thread_id": f"{user.id}-{uuid.uuid4().hex[:8]}"}},
    )

    return ChatResponse(
        reply=result.get("skill_output", ""),
        skill_used=result.get("selected_skill", "unknown"),
        comprehension=result.get("comprehension_signal", "no_response"),
        iteration_count=result.get("iteration_count", 0),
    )


# ── WebSocket Endpoint (requires token in query) ───────────────────

@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    """Streaming chat over WebSocket.

    Connect: ws://host/api/chat/ws?token=<JWT>
    Client sends: {"message": "...", "subject": "math"}
    Server streams: trace / skill / chunk / done / error events.
    """
    # Authenticate before accepting
    async with async_session() as db:
        user = await _get_user_from_ws_token(websocket, db)

    if not user:
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "type": "auth_error",
            "message": "Invalid or missing token. Connect with ?token=<JWT>",
        }))
        await websocket.close(code=4001)
        return

    await websocket.accept()
    logger.info("WebSocket connected: user=%s (%s)", user.username, user.role)

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            message = data.get("message", "")
            subject = data.get("subject", "math")
            images = data.get("images", [])  # list of base64 data-URL strings

            if not message.strip() and not images:
                await websocket.send_text(json.dumps({"type": "error", "message": "Empty message"}))
                continue

            # Build the human message: text-only, or vision-extracted when images present
            if images:
                # Extract question text from images via vision model, then
                # hand the extracted text to the (text-only) teaching agent.
                extracted = await _extract_text_from_images(images, message)
                if extracted:
                    combined = (
                        f"{message}\n\n[图片识别出的题目]\n{extracted}"
                        if message.strip() else extracted
                    )
                else:
                    combined = message or "（图片无法识别，请用文字描述题目）"
                human_message = HumanMessage(content=combined)
                logger.info("Vision extracted %d chars from %d image(s)", len(extracted), len(images))
            else:
                human_message = HumanMessage(content=message)

            # Load student profile from DB
            async with async_session() as db:
                profile = await profile_store.load(db, str(user.id))

            profile.total_messages += 1
            profile.primary_subject = subject

            state_dict = profile.to_state_dict()
            state_dict["subject"] = subject
            state_dict["role"] = user.role
            state_dict["iteration_count"] = 0

            thread_id = f"{user.id}-{uuid.uuid4().hex[:8]}"
            logger.info(
                "Processing: user=%s thread=%s images=%d",
                user.username, thread_id, len(images),
            )

            try:
                final_output = ""
                final_skill = ""
                final_comprehension = "no_response"
                final_iteration = 0

                async for event in _tutor_graph.astream_events(
                    {"messages": [human_message], **state_dict},
                    config={"configurable": {"thread_id": thread_id}},
                    version="v2",
                ):
                    evt_kind = event.get("event", "")
                    evt_name = event.get("name", "")
                    evt_data = event.get("data", {})

                    if evt_kind in ("on_chain_start", "on_chain_end") and evt_name in (
                        "assess", "router", "execute", "observe", "update"
                    ):
                        if evt_kind == "on_chain_start":
                            await websocket.send_text(json.dumps({
                                "type": "trace",
                                "node": evt_name,
                                "status": "started",
                            }, ensure_ascii=False))
                        elif evt_kind == "on_chain_end":
                            output = evt_data.get("output", {})
                            if evt_name == "router" and isinstance(output, dict):
                                final_skill = output.get("selected_skill", "")
                                await websocket.send_text(json.dumps({
                                    "type": "skill",
                                    "skill": final_skill,
                                    "layer": output.get("skill_layer", ""),
                                }, ensure_ascii=False))
                            elif evt_name == "execute" and isinstance(output, dict):
                                final_output = output.get("skill_output", "")
                                final_comprehension = output.get("comprehension_signal", "no_response")
                                if final_output:
                                    await websocket.send_text(json.dumps({
                                        "type": "chunk",
                                        "content": final_output,
                                    }, ensure_ascii=False))
                            elif evt_name == "assess" and isinstance(output, dict):
                                final_iteration = output.get("iteration_count", 0)

                    elif evt_kind == "on_chat_model_stream":
                        chunk = evt_data.get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            await websocket.send_text(json.dumps({
                                "type": "chunk",
                                "content": chunk.content,
                            }, ensure_ascii=False))

                # Persist profile + teaching event after graph completes
                async with async_session() as db:
                    # Update knowledge mastery if delta exists
                    # (update_node would set this in real implementation)
                    profile.total_messages = profile.total_messages  # already incremented
                    await profile_store.save(db, profile)

                    # Log teaching event
                    event_log = TeachingEventDB(
                        user_id=str(user.id),
                        skill_id=final_skill or "unknown",
                        student_message=message[:2000],
                        skill_output=final_output[:5000] if final_output else None,
                        comprehension=final_comprehension,
                        iteration_count=final_iteration,
                    )
                    db.add(event_log)
                    await db.commit()

                await websocket.send_text(json.dumps({
                    "type": "done",
                    "reply": "",
                    "comprehension": final_comprehension,
                    "skill_used": final_skill,
                    "iteration_count": final_iteration,
                }, ensure_ascii=False))

            except Exception as e:
                logger.exception("Graph execution error")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Processing error: {str(e)}",
                }, ensure_ascii=False))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: user=%s", user.username)
    except Exception as e:
        logger.exception("WebSocket error")
