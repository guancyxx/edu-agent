"""Curriculum package — knowledge tree loading and querying."""
from __future__ import annotations

from pathlib import Path

from app.curriculum.index import CurriculumIndex, KnowledgePoint, Chapter

__all__ = ["CurriculumIndex", "KnowledgePoint", "Chapter", "get_index"]

_index: CurriculumIndex | None = None


def get_index() -> CurriculumIndex:
    """Return the process-wide curriculum index (lazy, loaded once).

    Loads every ``*.yaml`` under ``app/curriculum/data/``. If the directory
    is missing the index stays empty — callers treat that as "no curriculum
    available" rather than an error.
    """
    global _index
    if _index is None:
        _index = CurriculumIndex()
        _index.load_directory(Path(__file__).parent / "data")
    return _index
