"""SM-2 spaced repetition algorithm.

Implements the SuperMemo-2 algorithm for scheduling review intervals
based on the quality of the student's recall response.

Quality ratings:
  0-2: Complete failure / forgot → reset to learning
  3-4: Struggled but recalled → short interval
  5:   Perfect recall → full interval growth
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class SM2Result:
    """Output of an SM-2 scheduling calculation."""
    review_count: int
    ease_factor: float    # stored as float (e.g. 2.5), not *1000
    interval_days: int
    next_review_at: datetime
    status: str           # learning / reviewing / mastered


def sm2_schedule(
    review_count: int,
    ease_factor: float,
    interval_days: int,
    quality: int,
    now: datetime | None = None,
) -> SM2Result:
    """Compute the next review schedule for a mistake entry.

    Args:
        review_count: Number of previous successful reviews.
        ease_factor: Current ease factor (e.g. 2.5). Minimum is 1.3.
        interval_days: Current interval in days.
        quality: Recall quality 0-5 (0=forgot, 5=perfect).
        now: Reference time (defaults to utcnow).
    Returns:
        SM2Result with updated scheduling fields.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    q = max(0, min(5, quality))

    # Update ease factor: EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = max(1.3, round(new_ef, 2))

    # Failed recall (quality < 3): reset to learning
    if q < 3:
        return SM2Result(
            review_count=0,
            ease_factor=new_ef,
            interval_days=1,
            next_review_at=now + timedelta(days=1),
            status="learning",
        )

    # Successful recall: advance
    new_count = review_count + 1

    if new_count == 1:
        new_interval = 1
    elif new_count == 2:
        new_interval = 3
    else:
        new_interval = max(1, round(interval_days * new_ef))

    # Mastered after 5 consecutive correct reviews with good quality
    new_status = "mastered" if new_count >= 5 and q >= 4 else "reviewing"

    return SM2Result(
        review_count=new_count,
        ease_factor=new_ef,
        interval_days=new_interval,
        next_review_at=now + timedelta(days=new_interval),
        status=new_status,
    )


def is_due(next_review_at: datetime, now: datetime | None = None) -> bool:
    """Check if a review is due."""
    if now is None:
        now = datetime.now(timezone.utc)
    return next_review_at <= now
