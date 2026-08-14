"""SQLAlchemy ORM models for the edu-agent platform."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, ForeignKey, JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """User account — student, parent, or teacher."""
    __tablename__ = "edu_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="student")  # student/parent/teacher
    grade = Column(Integer, nullable=False, default=7)
    display_name = Column(String(64), nullable=True)
    avatar_url = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True)
    is_disabled = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    profile = relationship("StudentProfileDB", back_populates="user", uselist=False)
    sessions = relationship("ChatSessionDB", back_populates="user")


class StudentProfileDB(Base):
    """Student learning profile stored as JSON."""
    __tablename__ = "edu_student_profiles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("edu_users.id"), primary_key=True)
    profile_data = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="profile")


class ChatSessionDB(Base):
    """A chat session between a user and the AI tutor."""
    __tablename__ = "edu_chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("edu_users.id"), nullable=False)
    subject = Column(String(32), nullable=False, default="math")
    title = Column(String(255), nullable=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="sessions")


class TeachingEventDB(Base):
    """Log of every skill execution — for analytics and A/B testing."""
    __tablename__ = "edu_teaching_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(64), nullable=True)
    skill_id = Column(String(128), nullable=False)
    skill_version = Column(String(32), nullable=False, default="1.0.0")
    student_message = Column(Text, nullable=True)
    skill_output = Column(Text, nullable=True)
    comprehension = Column(String(32), nullable=True)
    iteration_count = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class MistakeEntryDB(Base):
    """A single mistake record in the student's mistake notebook.

    Tracks wrong answers with spaced-repetition scheduling (SM-2 algorithm).
    Each entry represents one knowledge gap the student needs to review.
    """
    __tablename__ = "edu_mistake_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("edu_users.id"), nullable=False, index=True)
    subject = Column(String(32), nullable=False, default="math")
    question = Column(Text, nullable=False)
    student_answer = Column(Text, nullable=True)
    correct_answer = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    knowledge_point_id = Column(String(64), nullable=True)  # links to curriculum
    source = Column(String(32), nullable=False, default="chat")  # chat/manual/quiz

    # SM-2 spaced repetition fields
    review_count = Column(Integer, default=0)
    ease_factor = Column(Integer, default=2500)  # SM-2 ease * 1000 (e.g. 2.5 → 2500)
    interval_days = Column(Integer, default=1)
    next_review_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), default="learning")  # learning/reviewing/mastered

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
