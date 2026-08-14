"""Loader for ``.md`` skill files with YAML frontmatter.

A skill file looks like::

    ---
    name: concept-explain
    layer: atom
    category: explain
    description: Explain a concept simply with examples
    subject: math
    triggers:
      - {intent: explain}
      - {keyword: 什么是}
    inputs: [topic, student_question]
    outputs: [explanation]
    ---

    You are a tutor. Explain {{ topic }} to a {{ grade_level }} student.
    The student asked: {{ student_question }}

The loader walks ``atoms/``, ``molecules/``, ``domains/`` (recursively) and
``meta/`` subdirectories of the skills root, parses each ``.md`` file into a
:class:`SkillMeta`, and returns the full collection.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .schema import SkillMeta

__all__ = ["SkillLoader", "parse_frontmatter"]

logger = logging.getLogger(__name__)

# --- layout constants ------------------------------------------------------

#: Subdirectories under the skills root that we auto-discover.
SKILL_SUBDIRS: tuple[str, ...] = (
    "atoms",
    "molecules",
    "domains",  # walked recursively (domains/math/..., domains/english/...)
    "meta",
    "compounds",
)

#: Frontmatter delimiter regex. Matches an optional leading ``---\n`` block.
_FRONTMATTER_RE = re.compile(
    r"\A\s*---\s*\n(?P<fm>.*?)\n---\s*\n?(?P<body>.*)\Z",
    re.DOTALL,
)

#: Required frontmatter keys — missing any raises ``ValueError``.
_REQUIRED_FIELDS: tuple[str, ...] = ("name", "layer", "category", "description")

#: Fields stored as lists even when a single scalar is given.
_LIST_FIELDS: tuple[str, ...] = ("inputs", "outputs", "steps")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split raw ``.md`` text into ``(frontmatter_dict, body)``.

    If no frontmatter is present, returns ``({}, text)``.

    Args:
        text: Raw file contents.
    Returns:
        Tuple of parsed frontmatter dict and the remaining markdown body.
    Raises:
        yaml.YAMLError: If the frontmatter block is malformed YAML.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fm_text = match.group("fm")
    body = match.group("body").strip()
    data = yaml.safe_load(fm_text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Frontmatter must be a YAML mapping, got {type(data).__name__}")
    return data, body


def _coerce_list(value: Any) -> list[Any]:
    """Normalise scalar / list / None into a ``list``."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class SkillLoader:
    """Discovers and parses ``.md`` skill files into :class:`SkillMeta`.

    Usage::

        loader = SkillLoader(project_root=Path("/path/to/edu-agent"))
        skills = loader.load_directory()           # auto-discover
        skills = loader.load_file("skills/atoms/concept-explain.md")
    """

    def __init__(self, project_root: Path | str | None = None) -> None:
        """Initialise the loader.

        Args:
            project_root: Root of the edu-agent repo. If ``None``, the loader
                will try to auto-detect it (see :meth:`_default_skills_dir`).
        """
        if project_root is None:
            self.project_root = self._find_project_root()
        else:
            self.project_root = Path(project_root).resolve()
        self.skills_dir = self.project_root / "skills"

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def load_directory(self, path: Path | str | None = None) -> list[SkillMeta]:
        """Walk known subdirectories and load every ``.md`` skill file.

        Args:
            path: Skills root directory. Defaults to ``<project_root>/skills``.
        Returns:
            List of parsed :class:`SkillMeta`. Files that fail to parse are
            skipped with a warning (never raises for a single bad file).
        """
        root = Path(path).resolve() if path else self.skills_dir
        if not root.is_dir():
            logger.warning("Skills directory does not exist: %s", root)
            return []

        skills: list[SkillMeta] = []
        seen_ids: set[str] = set()

        for md_file in sorted(root.rglob("*.md")):
            # Skip files that are clearly not skills (e.g. README in skills/)
            if md_file.name.upper() in {"README.MD", "INDEX.MD"}:
                continue
            try:
                meta = self.load_file(md_file)
            except Exception as exc:  # noqa: BLE001 — log and continue
                logger.warning("Skipping skill file %s: %s", md_file, exc)
                continue
            if meta.id in seen_ids:
                logger.warning(
                    "Duplicate skill id %r in %s — ignoring later occurrence",
                    meta.id,
                    md_file,
                )
                continue
            seen_ids.add(meta.id)
            skills.append(meta)

        logger.info("Loaded %d skills from %s", len(skills), root)
        return skills

    def load_file(self, path: Path | str) -> SkillMeta:
        """Parse a single ``.md`` skill file into :class:`SkillMeta`.

        Args:
            path: Absolute or relative path to the ``.md`` file.
        Returns:
            Parsed :class:`SkillMeta`.
        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If required frontmatter fields are missing.
            yaml.YAMLError: If frontmatter YAML is malformed.
        """
        file_path = Path(path).resolve()
        raw = file_path.read_text(encoding="utf-8")
        meta = self._build_meta(raw, file_path)
        return meta

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _build_meta(self, raw: str, file_path: Path) -> SkillMeta:
        """Convert raw file text + path into a validated :class:`SkillMeta`."""
        fm, body = parse_frontmatter(raw)

        # Validate required fields
        missing = [f for f in _REQUIRED_FIELDS if f not in fm]
        if missing:
            raise ValueError(
                f"Skill {file_path.name} missing required fields: {', '.join(missing)}"
            )

        # Derive layer from parent directory if not explicitly set.
        layer = fm.get("layer") or self._infer_layer(file_path)
        if layer not in ("atom", "molecule", "compound"):
            raise ValueError(
                f"Skill {file_path.name} has invalid layer {layer!r}; "
                "expected atom/molecule/compound"
            )

        meta = SkillMeta(
            name=str(fm["name"]),
            layer=layer,
            category=str(fm["category"]),
            description=str(fm["description"]),
            version=str(fm.get("version", "1.0.0")),
            status=str(fm.get("status", "approved")),
            subject=str(fm.get("subject", "general")),
            triggers=list(fm.get("triggers") or []),
            inputs=_coerce_list(fm.get("inputs")),
            outputs=_coerce_list(fm.get("outputs")),
            deps=dict(fm.get("deps") or {}),
            steps=_coerce_list(fm.get("steps")),
            system_prompt=str(fm.get("system_prompt", "")),
            body=body,
        )
        return meta

    @staticmethod
    def _infer_layer(file_path: Path) -> str:
        """Guess the layer from the directory name (atoms→atom, etc.)."""
        parts = file_path.parts
        for part in parts:
            lower = part.lower()
            if lower in ("atoms", "atom"):
                return "atom"
            if lower in ("molecules", "molecule"):
                return "molecule"
            if lower in ("compounds", "compound"):
                return "compound"
        return "atom"  # sensible default for domains/meta

    @staticmethod
    def _find_project_root() -> Path:
        """Walk up from CWD to locate the repo root (contains ``skills/``)."""
        cwd = Path.cwd()
        for candidate in [cwd, *cwd.parents]:
            if (candidate / "skills").is_dir():
                return candidate
            if (candidate / "backend" / "app" / "skills").is_dir():
                return candidate
        # Fall back to cwd so callers get a clear error downstream.
        return cwd
