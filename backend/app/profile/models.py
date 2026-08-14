"""Student profile data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StudentProfile:
    """Complete student learning profile.

    This is the adaptive learning memory — persisted to PostgreSQL
    and loaded into TutorState at the start of each graph run.
    """
    user_id: str
    grade: int = 7

    # Knowledge mastery: kp_id → 0.0-1.0
    knowledge_mastery: dict[str, float] = field(default_factory=dict)

    # Emotion window: last N turns (rolling)
    emotion_history: list[dict] = field(default_factory=list)

    # Ability assessment
    ability_level: str = "beginner"  # beginner/intermediate/advanced
    learning_style: str = "example_first"  # example_first/theory_first/practice_first

    # Error patterns
    recent_mistakes: list[dict] = field(default_factory=list)

    # Preferred subject
    primary_subject: str = "math"

    # Stats
    total_sessions: int = 0
    total_messages: int = 0
    streak_days: int = 0

    def get_emotion_snapshot(self) -> dict[str, float]:
        """Average emotion scores from the last 5 turns."""
        if not self.emotion_history:
            return {"frustration": 0.0, "confusion": 0.0, "confidence": 0.5, "excitement": 0.0}
        recent = self.emotion_history[-5:]
        return {
            key: sum(turn.get(key, 0) for turn in recent) / len(recent)
            for key in ("frustration", "confusion", "confidence", "excitement")
        }

    def get_weak_topics(self, threshold: float = 0.4) -> list[str]:
        """Knowledge points below mastery threshold."""
        return [kp_id for kp_id, score in self.knowledge_mastery.items() if score < threshold]

    def update_mastery(self, kp_id: str, delta: float) -> None:
        """Apply a mastery delta, clamped to [0.0, 1.0]."""
        current = self.knowledge_mastery.get(kp_id, 0.0)
        self.knowledge_mastery[kp_id] = max(0.0, min(1.0, current + delta))

    def to_state_dict(self) -> dict:
        """Convert to a dict suitable for TutorState updates."""
        return {
            "student_id": self.user_id,
            "grade": self.grade,
            "knowledge_mastery": self.knowledge_mastery,
            "emotion_state": self.get_emotion_snapshot(),
            "ability_level": self.ability_level,
            "learning_style": self.learning_style,
            "recent_mistakes": self.recent_mistakes[-10:],
        }
