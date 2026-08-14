"""In-memory index over loaded skills for fast lookup and routing.

``SkillCatalog`` is built once at startup from the list of :class:`SkillMeta`
returned by :class:`~edu_agent.app.skills.loader.SkillLoader`. The router node
then queries it with the student's subject, ability level, and current topics
to get a ranked list of :class:`SkillCandidate`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Literal, Protocol

from .schema import SkillCandidate, SkillMeta

__all__ = ["SkillCatalog", "LLMProtocol"]

LayerType = Literal["atom", "molecule", "compound"]


class LLMProtocol(Protocol):
    """Minimal interface a callable must satisfy to be used as ``llm``.

    Implementations may be a LangChain ``Runnable``, a plain function, or any
    object with a ``__call__`` that accepts ``(prompt: str)`` and returns a
    string (or an object with ``.content``).
    """

    def __call__(self, prompt: str, **kwargs: Any) -> str:  # pragma: no cover
        ...


class SkillCatalog:
    """Indexes skills for O(1) id lookup and fast filtered listing.

    The catalog is immutable after construction — rebuild it when skills
    change on disk (e.g. via a hot-reload hook).
    """

    def __init__(self, skills: Iterable[SkillMeta]) -> None:
        """Build indexes from an iterable of :class:`SkillMeta`.

        Args:
            skills: Loaded skill metadatas.
        """
        self._skills: list[SkillMeta] = list(skills)
        self._by_id: dict[str, SkillMeta] = {s.id: s for s in self._skills}
        self._by_layer: dict[str, list[SkillMeta]] = defaultdict(list)
        self._by_subject: dict[str, list[SkillMeta]] = defaultdict(list)
        for s in self._skills:
            self._by_layer[s.layer].append(s)
            self._by_subject[s.subject].append(s)

    # ------------------------------------------------------------------
    # simple lookups
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Total number of indexed skills."""
        return len(self._skills)

    @property
    def all(self) -> list[SkillMeta]:
        """All indexed skills (read-only view)."""
        return list(self._skills)

    def get(self, skill_id: str) -> SkillMeta | None:
        """Fetch a skill by id (``name``). Returns ``None`` if not found."""
        return self._by_id.get(skill_id)

    def list_by_layer(self, layer: LayerType) -> list[SkillMeta]:
        """All skills at a given graph layer."""
        return list(self._by_layer.get(layer, ()))

    def list_by_subject(self, subject: str) -> list[SkillMeta]:
        """All skills for a subject (``math``, ``english``, ...).

        ``general``-subject skills are always included in results for any
        subject, since they apply universally.
        """
        matched = list(self._by_subject.get(subject, ()))
        if subject != "general":
            matched.extend(self._by_subject.get("general", ()))
        return matched

    # ------------------------------------------------------------------
    # routing / candidate scoring
    # ------------------------------------------------------------------

    def get_candidates(
        self,
        subject: str,
        ability_level: str = "average",
        topics: list[str] | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[SkillCandidate]:
        """Rank all applicable skills by relevance to the current context.

        Scoring is a lightweight heuristic (no LLM call) combining:
        - **subject match** (1.0 exact, 0.5 for ``general``)
        - **trigger keyword overlap** with topics (0–0.3)
        - **ability-level hint** from skill name/category (0–0.2)

        Args:
            subject: Active subject (``math``/``english``/``physics``/``general``).
            ability_level: Student ability — ``weak``/``average``/``strong``.
            topics: Current topic keywords from the student message.
            limit: Max candidates to return.
            min_score: Discard candidates below this threshold.
        Returns:
            Candidates sorted descending by score, then by name.
        """
        topics = topics or []
        topic_lower = {t.lower() for t in topics}
        candidates: list[SkillCandidate] = []

        for skill in self._skills:
            score, reason = self._score_skill(
                skill, subject, ability_level, topic_lower
            )
            if score < min_score:
                continue
            candidates.append(SkillCandidate(meta=skill, score=score, reason=reason))

        candidates.sort(key=lambda c: (-c.score, c.meta.name))
        return candidates[:limit]

    def to_menu(self, layer: LayerType | None = None) -> list[dict[str, str]]:
        """Compact menu for the LLM router system prompt.

        Args:
            layer: Restrict to a single layer (default: all).
        Returns:
            List of ``{"id", "name", "description"}`` dicts.
        """
        skills = self._skills if layer is None else self.list_by_layer(layer)
        return [
            {"id": s.id, "name": s.name, "description": s.description}
            for s in skills
        ]

    # ------------------------------------------------------------------
    # scoring internals
    # ------------------------------------------------------------------

    @staticmethod
    def _score_skill(
        skill: SkillMeta,
        subject: str,
        ability_level: str,
        topic_lower: set[str],
    ) -> tuple[float, str]:
        """Heuristic relevance score in ``[0, 1]``."""
        score = 0.0
        reasons: list[str] = []

        # --- subject match (weight: up to 1.0) ---
        if skill.subject == subject:
            score += 0.5
            reasons.append(f"subject:{skill.subject}")
        elif skill.subject == "general":
            score += 0.25
            reasons.append("subject:general")
        elif subject == "general":
            score += 0.1
            reasons.append("query:general")

        # --- trigger / topic overlap (weight: up to 0.3) ---
        trigger_keywords: set[str] = set()
        for trig in skill.triggers:
            kw = trig.get("keyword") or trig.get("topic")
            if kw:
                trigger_keywords.add(str(kw).lower())
        if topic_lower and trigger_keywords:
            overlap = topic_lower & trigger_keywords
            if overlap:
                bonus = min(0.3, 0.1 * len(overlap))
                score += bonus
                reasons.append(f"topic:{','.join(sorted(overlap))}")
        # Also check if skill name/description mentions a topic directly.
        skill_text = f"{skill.name} {skill.category} {skill.description}".lower()
        if topic_lower:
            name_hits = {t for t in topic_lower if t in skill_text}
            if name_hits:
                bonus = min(0.2, 0.05 * len(name_hits))
                score += bonus
                reasons.append(f"name:{','.join(sorted(name_hits))}")

        # --- ability-level adjustment (weight: up to 0.2) ---
        level = ability_level.lower()
        if level == "weak" and any(
            tag in skill.name or tag in skill.category
            for tag in ("hint", "guided", "step", "scaffold")
        ):
            score += 0.2
            reasons.append("ability:weak+scaffold")
        elif level == "strong" and any(
            tag in skill.name or tag in skill.category
            for tag in ("challenge", "extension", "advanced", "check")
        ):
            score += 0.2
            reasons.append("ability:strong+challenge")

        return min(score, 1.0), "; ".join(reasons) if reasons else "default"
