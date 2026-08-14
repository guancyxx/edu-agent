"""Chat router — HTTP and WebSocket endpoints for tutoring conversations.

The WebSocket endpoint streams LangGraph events to the frontend in real-time,
providing token-by-token output, skill execution traces, and comprehension signals.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel

from app.engine.graph import build_tutor_graph
from app.skills.loader import SkillLoader
from app.skills.catalog import SkillCatalog

logger = logging.getLogger("edu-agent.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ── Shared singletons ──────────────────────────────────────────────

_skill_loader = SkillLoader()
_loaded_skills = _skill_loader.load_directory("../skills")
_catalog = SkillCatalog(_loaded_skills)
_tutor_graph = build_tutor_graph()


# ── HTTP Models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """HTTP chat request (non-streaming fallback)."""
    message: str
    student_id: str = "anonymous"
    subject: str = "math"
    grade: int = 7
    role: str = "student"


class ChatResponse(BaseModel):
    """HTTP chat response."""
    reply: str
    skill_used: str
    comprehension: str
    iteration_count: int


# ── HTTP Endpoint ──────────────────────────────────────────────────

@router.post("/send", response_model=ChatResponse)
async def send_message(req: ChatRequest):
    """Non-streaming chat endpoint (for testing / fallback)."""
    result = await _tutor_graph.ainvoke(
        {
            "messages": [HumanMessage(content=req.message)],
            "student_id": req.student_id,
            "subject": req.subject,
            "grade": req.grade,
            "role": req.role,
            "iteration_count": 0,
        },
        config={"configurable": {"thread_id": f"{req.student_id}-{uuid.uuid4().hex[:8]}"}},
    )

    return ChatResponse(
        reply=result.get("skill_output", ""),
        skill_used=result.get("selected_skill", "unknown"),
        comprehension=result.get("comprehension_signal", "no_response"),
        iteration_count=result.get("iteration_count", 0),
    )


# ── WebSocket Endpoint ─────────────────────────────────────────────

@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    """Streaming chat over WebSocket.

    Client sends JSON: {"message": "...", "student_id": "...", "subject": "math", "grade": 7}
    Server streams events:
      - {"type": "trace", "node": "assess", "message": "..."}
      - {"type": "skill", "skill": "concept-explain", "layer": "atom"}
      - {"type": "chunk", "content": "..."}   (token-by-token)
      - {"type": "done", "reply": "...", "comprehension": "understood"}
      - {"type": "error", "message": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket connected")

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            message = data.get("message", "")
            student_id = data.get("student_id", "anonymous")
            subject = data.get("subject", "math")
            grade = data.get("grade", 7)
            role = data.get("role", "student")

            if not message.strip():
                await websocket.send_text(json.dumps({"type": "error", "message": "Empty message"}))
                continue

            thread_id = f"{student_id}-{uuid.uuid4().hex[:8]}"
            logger.info("Processing: student=%s thread=%s", student_id, thread_id)

            # Send trace events as the graph executes
            try:
                # Stream events from LangGraph and collect final output
                final_output = ""
                final_skill = ""
                final_comprehension = "no_response"
                final_iteration = 0

                async for event in _tutor_graph.astream_events(
                    {
                        "messages": [HumanMessage(content=message)],
                        "student_id": student_id,
                        "subject": subject,
                        "grade": grade,
                        "role": role,
                        "iteration_count": 0,
                    },
                    config={"configurable": {"thread_id": thread_id}},
                    version="v2",
                ):
                    evt_kind = event.get("event", "")
                    evt_name = event.get("name", "")
                    evt_data = event.get("data", {})

                    # Node started/finished → trace event
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
                                # Send the full output as chunks
                                if final_output:
                                    await websocket.send_text(json.dumps({
                                        "type": "chunk",
                                        "content": final_output,
                                    }, ensure_ascii=False))
                            elif evt_name == "assess" and isinstance(output, dict):
                                final_iteration = output.get("iteration_count", 0)

                    # LLM token streaming
                    elif evt_kind == "on_chat_model_stream":
                        chunk = evt_data.get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            await websocket.send_text(json.dumps({
                                "type": "chunk",
                                "content": chunk.content,
                            }, ensure_ascii=False))

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
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception("WebSocket error")
