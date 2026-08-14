"""Skill metadata dataclasses for the edu-agent skill system.

Defines the in-memory representation of a skill parsed from a ``.md`` file
with YAML frontmatter, plus a scored candidate wrapper used by the router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["SkillMeta", "SkillCandidate", "LayerType", "SubjectType"]

LayerType = Literal["atom", "molecule", "compound"]
SubjectType = Literal["math", "english", "physics", "general"]


@dataclass
class SkillMeta:
    """Metadata for a single skill, parsed from a ``.md`` frontmatter block.

    Attributes:
        name: Human-readable identifier, e.g. ``"concept-explain"``.
        layer: Graph layer — ``atom`` (single LLM call), ``molecule``
            (multi-step subgraph), or ``compound`` (full session).
        category: Functional grouping, e.g. ``"explain"``, ``"hint"``.
        description: One-line summary used in router prompts.
        version: Semver string.
        status: Lifecycle status — ``approved`` | ``draft`` | ``deprecated``.
        subject: Subject domain filter.
        triggers: Patterns that auto-activate this skill. Each item is a
            dict, e.g. ``{"keyword": "不会"}`` or ``{"intent": "ask_help"}``.
        inputs: State keys this skill reads from.
        outputs: State keys this skill writes to.
        deps: Dependency graph for molecules/compounds — maps a node name
            to the skill ``id`` it should run, e.g. ``{"assess": "student-assess"}``.
        steps: Ordered list of human-readable step descriptions (molecules).
        system_prompt: Override for the LLM system message; falls back to a
            global default when empty.
        body: Raw markdown body after frontmatter — the Jinja2 prompt
            template rendered at runtime.
    """

    name: str
    layer: LayerType
    category: str
    description: str
    version: str = "1.0.0"
    status: str = "approved"
    subject: str = "general"  # math/english/physics/general
    triggers: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    deps: dict[str, str] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)  # for molecules
    system_prompt: str = ""
    body: str = ""  # raw markdown body (template)

    @property
    def id(self) -> str:
        """Stable identifier — currently equal to ``name``.

        Keeping this as a property lets us later derive the id from the
        file path (e.g. ``math/algebra-basics``) without touching callers.
        """
        return self.name

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (for logging / JSON responses)."""
        return {
            "id": self.id,
            "name": self.name,
            "layer": self.layer,
            "category": self.category,
            "description": self.description,
            "version": self.version,
            "status": self.status,
            "subject": self.subject,
            "triggers": self.triggers,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "deps": self.deps,
            "steps": self.steps,
            "system_prompt": self.system_prompt,
        }


@dataclass
class SkillCandidate:
    """A skill paired with its relevance score for the current context.

    Produced by :meth:`SkillCatalog.get_candidates` and consumed by the
    router node to pick which skill(s) to execute.

    Attributes:
        meta: The underlying :class:`SkillMeta`.
        score: Relevance in ``[0.0, 1.0]`` — higher is more relevant.
        reason: Short human-readable justification for the score, useful
            for debugging router decisions.
    """

    meta: SkillMeta
    score: float = 0.0
    reason: str = ""
