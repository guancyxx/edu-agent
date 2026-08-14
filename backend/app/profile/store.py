"""Profile store — PostgreSQL persistence for student profiles.

Profiles are stored as JSON in a single column for simplicity.
As the system grows, individual fields can be promoted to columns.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.models import StudentProfile

logger = logging.getLogger("edu-agent.profile")

DEFAULT_PROFILE_SQL = text("""
    INSERT INTO edu_student_profiles (user_id, profile_data)
    VALUES (CAST(:user_id AS UUID), :data)
    ON CONFLICT (user_id) DO NOTHING
""")

GET_PROFILE_SQL = text("""
    SELECT profile_data FROM edu_student_profiles WHERE user_id = CAST(:user_id AS UUID)
""")

UPSERT_PROFILE_SQL = text("""
    INSERT INTO edu_student_profiles (user_id, profile_data, updated_at)
    VALUES (CAST(:user_id AS UUID), :data, NOW())
    ON CONFLICT (user_id)
    DO UPDATE SET profile_data = EXCLUDED.profile_data, updated_at = NOW()
""")


class ProfileStore:
    """Async profile storage backed by PostgreSQL."""

    async def load(self, db: AsyncSession, user_id: str) -> StudentProfile:
        """Load a student profile, or create a default one."""
        result = await db.execute(GET_PROFILE_SQL, {"user_id": user_id})
        row = result.fetchone()

        if row:
            data = json.loads(row[0])
            return StudentProfile(**data)

        # Create default profile
        profile = StudentProfile(user_id=user_id)
        await self.save(db, profile)
        return profile

    async def save(self, db: AsyncSession, profile: StudentProfile) -> None:
        """Persist a student profile."""
        data = json.dumps({
            "user_id": profile.user_id,
            "grade": profile.grade,
            "knowledge_mastery": profile.knowledge_mastery,
            "emotion_history": profile.emotion_history,
            "ability_level": profile.ability_level,
            "learning_style": profile.learning_style,
            "recent_mistakes": profile.recent_mistakes,
            "primary_subject": profile.primary_subject,
            "total_sessions": profile.total_sessions,
            "total_messages": profile.total_messages,
            "streak_days": profile.streak_days,
        }, ensure_ascii=False)

        await db.execute(UPSERT_PROFILE_SQL, {"user_id": profile.user_id, "data": data})
        await db.commit()
        logger.debug("Saved profile for user %s", profile.user_id)


# Singleton
profile_store = ProfileStore()
