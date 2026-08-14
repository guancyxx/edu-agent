"""Curriculum index — loads YAML knowledge trees and provides query APIs."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("edu-agent.curriculum")


class KnowledgePoint:
    """A single knowledge point in the curriculum tree."""

    __slots__ = ("id", "title", "difficulty", "prerequisites", "description", "chapter_id")

    def __init__(self, kp_dict: dict, chapter_id: str):
        self.id: str = kp_dict["id"]
        self.title: str = kp_dict["title"]
        self.difficulty: int = kp_dict.get("difficulty", 1)
        self.prerequisites: list[str] = kp_dict.get("prerequisites", [])
        self.description: str = kp_dict.get("description", "")
        self.chapter_id: str = chapter_id

    def __repr__(self) -> str:
        return f"KP({self.id}: {self.title})"


class Chapter:
    """A chapter containing knowledge points."""

    __slots__ = ("id", "title", "knowledge_points")

    def __init__(self, ch_dict: dict):
        self.id: str = ch_dict["id"]
        self.title: str = ch_dict["title"]
        self.knowledge_points: list[KnowledgePoint] = [
            KnowledgePoint(kp, self.id) for kp in ch_dict.get("knowledge_points", [])
        ]


class CurriculumIndex:
    """In-memory index of the curriculum knowledge tree."""

    def __init__(self) -> None:
        self._chapters: dict[str, Chapter] = {}
        self._kp_index: dict[str, KnowledgePoint] = {}
        self._by_subject: dict[str, list[Chapter]] = {}
        self._by_subject_grade: dict[str, list[Chapter]] = {}

    def load_directory(self, dir_path: str | Path) -> int:
        """Load all YAML files from a directory. Returns count of knowledge points."""
        dir_path = Path(dir_path)
        if not dir_path.exists():
            logger.warning("Curriculum directory not found: %s", dir_path)
            return 0

        count = 0
        for yaml_file in sorted(dir_path.glob("*.yaml")):
            count += self._load_file(yaml_file)

        logger.info("Loaded %d knowledge points from %s", count, dir_path)
        return count

    def _load_file(self, yaml_path: Path) -> int:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not data:
            return 0

        subject: str = data.get("subject", "general")
        grade: int = data.get("grade", 0)
        key = f"{subject}-{grade}"

        chapters = []
        for ch_dict in data.get("chapters", []):
            chapter = Chapter(ch_dict)
            self._chapters[chapter.id] = chapter
            for kp in chapter.knowledge_points:
                self._kp_index[kp.id] = kp
            chapters.append(chapter)

        self._by_subject_grade[key] = chapters
        self._by_subject.setdefault(subject, []).extend(chapters)

        return sum(len(ch.knowledge_points) for ch in chapters)

    def get_kp(self, kp_id: str) -> Optional[KnowledgePoint]:
        """Look up a knowledge point by ID."""
        return self._kp_index.get(kp_id)

    def get_chapter(self, chapter_id: str) -> Optional[Chapter]:
        """Look up a chapter by ID."""
        return self._chapters.get(chapter_id)

    def list_by_subject(self, subject: str) -> list[Chapter]:
        """All chapters for a subject."""
        return self._by_subject.get(subject, [])

    def list_by_grade(self, subject: str, grade: int) -> list[Chapter]:
        """Chapters for a specific subject + grade."""
        return self._by_subject_grade.get(f"{subject}-{grade}", [])

    def get_prerequisites(self, kp_id: str) -> list[KnowledgePoint]:
        """Get prerequisite knowledge points (one level deep)."""
        kp = self._kp_index.get(kp_id)
        if not kp:
            return []
        return [self._kp_index[pid] for pid in kp.prerequisites if pid in self._kp_index]

    def get_unmastered(self, kp_ids: list[str], mastery: dict[str, float], threshold: float = 0.6) -> list[KnowledgePoint]:
        """Find knowledge points below mastery threshold."""
        return [
            self._kp_index[kid]
            for kid in kp_ids
            if kid in self._kp_index and mastery.get(kid, 0.0) < threshold
        ]
