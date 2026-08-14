"""Skill runtime package for the edu-agent K12 tutoring platform.

Public API::

    from app.skills import SkillLoader, SkillCatalog, SkillMeta, SkillResult

Layered architecture (mirrors MagicEdit Skill Graphs 2.0):

- **atom** — a single LLM call (explain, hint, check, ...).
- **molecule** — a multi-step teaching sequence (guided solve, gap fill).
- **compound** — a full session blueprint (training-session.yaml).

Skills are ``.md`` files with YAML frontmatter; the body is a Jinja2 prompt
template rendered with the student state at runtime.
"""

from __future__ import annotations

from .catalog import SkillCatalog
from .loader import SkillLoader, parse_frontmatter
from .runner import SkillResult, run, run_atom, run_molecule
from .schema import SkillCandidate, SkillMeta

__all__ = [
    "SkillLoader",
    "SkillCatalog",
    "SkillMeta",
    "SkillCandidate",
    "SkillResult",
    "run",
    "run_atom",
    "run_molecule",
    "parse_frontmatter",
]

__version__ = "1.0.0"
