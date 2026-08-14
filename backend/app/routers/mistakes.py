"""Mistake notebook router — CRUD + spaced repetition review endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MistakeEntryDB
from app.routers.auth import get_current_user
from app.models import User
from app.spaced_repetition import sm2_schedule, is_due

logger = logging.getLogger("edu-agent.mistakes")

router = APIRouter(prefix="/api/mistakes", tags=["mistakes"])


# ── Models ─────────────────────────────────────────────────────────

class MistakeCreate(BaseModel):
    subject: str = "math"
    question: str
    student_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    knowledge_point_id: Optional[str] = None
    source: str = "chat"


class MistakeOut(BaseModel):
    id: int
    subject: str
    question: str
    student_answer: Optional[str]
    correct_answer: Optional[str]
    explanation: Optional[str]
    knowledge_point_id: Optional[str]
    review_count: int
    ease_factor: float
    interval_days: int
    next_review_at: datetime
    last_reviewed_at: Optional[datetime]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewRequest(BaseModel):
    quality: int = Field(ge=0, le=5, description="0=forgot, 3=hard, 5=perfect")


class ReviewResponse(BaseModel):
    next_review_at: datetime
    interval_days: int
    status: str
    review_count: int
    ease_factor: float


class StatsResponse(BaseModel):
    total: int
    learning: int
    reviewing: int
    mastered: int
    due_today: int


# ── Helper ─────────────────────────────────────────────────────────

def _ease_to_float(stored: int) -> float:
    """Convert DB ease_factor (int * 1000) to float."""
    return round(stored / 1000.0, 2)


def _ease_to_int(ef: float) -> int:
    """Convert float ease_factor to DB int (* 1000)."""
    return int(ef * 1000)


def _entry_to_out(e: MistakeEntryDB) -> MistakeOut:
    return MistakeOut(
        id=e.id,
        subject=e.subject,
        question=e.question,
        student_answer=e.student_answer,
        correct_answer=e.correct_answer,
        explanation=e.explanation,
        knowledge_point_id=e.knowledge_point_id,
        review_count=e.review_count,
        ease_factor=_ease_to_float(e.ease_factor),
        interval_days=e.interval_days,
        next_review_at=e.next_review_at,
        last_reviewed_at=e.last_reviewed_at,
        status=e.status,
        created_at=e.created_at,
    )


# ── Endpoints ──────────────────────────────────────────────────────

@router.get("", response_model=list[MistakeOut])
async def list_mistakes(
    subject: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all mistake entries for the current user."""
    q = select(MistakeEntryDB).where(MistakeEntryDB.user_id == user.id)
    if subject:
        q = q.where(MistakeEntryDB.subject == subject)
    if status_filter:
        q = q.where(MistakeEntryDB.status == status_filter)
    q = q.order_by(MistakeEntryDB.created_at.desc())
    result = await db.execute(q)
    return [_entry_to_out(e) for e in result.scalars().all()]


@router.get("/due", response_model=list[MistakeOut])
async def list_due_reviews(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List mistake entries due for review."""
    now = datetime.now(timezone.utc)
    q = (
        select(MistakeEntryDB)
        .where(and_(
            MistakeEntryDB.user_id == user.id,
            MistakeEntryDB.status != "mastered",
            MistakeEntryDB.next_review_at <= now,
        ))
        .order_by(MistakeEntryDB.next_review_at.asc())
        .limit(limit)
    )
    result = await db.execute(q)
    return [_entry_to_out(e) for e in result.scalars().all()]


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get mistake notebook statistics."""
    base = select(MistakeEntryDB).where(MistakeEntryDB.user_id == user.id)

    total_r = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_r.scalar() or 0

    learning_r = await db.execute(
        select(func.count()).select_from(
            base.where(MistakeEntryDB.status == "learning").subquery()
        )
    )
    learning = learning_r.scalar() or 0

    reviewing_r = await db.execute(
        select(func.count()).select_from(
            base.where(MistakeEntryDB.status == "reviewing").subquery()
        )
    )
    reviewing = reviewing_r.scalar() or 0

    mastered_r = await db.execute(
        select(func.count()).select_from(
            base.where(MistakeEntryDB.status == "mastered").subquery()
        )
    )
    mastered = mastered_r.scalar() or 0

    now = datetime.now(timezone.utc)
    due_r = await db.execute(
        select(func.count()).select_from(
            base.where(and_(
                MistakeEntryDB.status != "mastered",
                MistakeEntryDB.next_review_at <= now,
            )).subquery()
        )
    )
    due_today = due_r.scalar() or 0

    return StatsResponse(
        total=total, learning=learning, reviewing=reviewing,
        mastered=mastered, due_today=due_today,
    )


@router.post("", response_model=MistakeOut, status_code=status.HTTP_201_CREATED)
async def create_mistake(
    req: MistakeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually add a mistake entry."""
    entry = MistakeEntryDB(
        user_id=user.id,
        subject=req.subject,
        question=req.question,
        student_answer=req.student_answer,
        correct_answer=req.correct_answer,
        explanation=req.explanation,
        knowledge_point_id=req.knowledge_point_id,
        source=req.source,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_to_out(entry)


@router.post("/{entry_id}/review", response_model=ReviewResponse)
async def review_mistake(
    entry_id: int,
    req: ReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a review for a mistake entry. Updates SM-2 schedule."""
    result = await db.execute(
        select(MistakeEntryDB).where(and_(
            MistakeEntryDB.id == entry_id,
            MistakeEntryDB.user_id == user.id,
        ))
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Mistake entry not found")

    sm2 = sm2_schedule(
        review_count=entry.review_count,
        ease_factor=_ease_to_float(entry.ease_factor),
        interval_days=entry.interval_days,
        quality=req.quality,
    )

    entry.review_count = sm2.review_count
    entry.ease_factor = _ease_to_int(sm2.ease_factor)
    entry.interval_days = sm2.interval_days
    entry.next_review_at = sm2.next_review_at
    entry.last_reviewed_at = datetime.now(timezone.utc)
    entry.status = sm2.status

    await db.commit()

    logger.info(
        "Mistake #%d reviewed: quality=%d → interval=%dd status=%s",
        entry_id, req.quality, sm2.interval_days, sm2.status,
    )

    return ReviewResponse(
        next_review_at=sm2.next_review_at,
        interval_days=sm2.interval_days,
        status=sm2.status,
        review_count=sm2.review_count,
        ease_factor=sm2.ease_factor,
    )


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mistake(
    entry_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a mistake entry."""
    result = await db.execute(
        select(MistakeEntryDB).where(and_(
            MistakeEntryDB.id == entry_id,
            MistakeEntryDB.user_id == user.id,
        ))
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(entry)
    await db.commit()
