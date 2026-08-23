"""Molecule execution — expand frontmatter ``steps`` into a real LangGraph subgraph.

A molecule skill declares an ordered list of atom skill ids in its frontmatter
(``steps: [hint-generate, concept-explain, knowledge-check]``). This module
turns that declaration into a linear ``StateGraph`` — one node per step, wired
``START → step_0 → … → step_N → END`` — and runs it with ``ainvoke``.

Design decisions (A2, 2026-08-23):

* **Real subgraph, linear topology.** No conditional edges in this iteration —
  reactive branching (``needs_concept`` style) needs student input mid-flight
  and belongs to the HITL work (B1, ``interrupt()``). The builder is generic:
  any molecule's ``steps`` compile through the same code path, so adding
  conditional edges later extends rather than rewrites it.
* **Step-to-step state passing is hybrid.** Every step renders against the
  *shared* context (the caller's ``skill_state``, already injected by
  ``execute_node``), plus two extra keys for steps ≥ 2: ``previous_output``
  (last step's output) and ``previous_outputs`` (all prior ``{skill, output}``).
  Templates that don't reference them are unaffected (Jinja renders empty).
* **The molecule body becomes the system prompt** for every step, so the
  Socratic persona/rules in ``guided-solve.md`` shape each atom call.
* **Graph cache is keyed on topology only** ``(skill.name, steps tuple)``.
  Per-request data (rendered system prompt, llm instance) flows through
  ``MoleculeState`` at invoke time — a cached graph never bakes in one
  student's context.
* **Fallback.** If ``steps`` is empty or none resolve against the catalog,
  the molecule degrades to a single ``run_atom`` call (the pre-A2 behaviour)
  and the result metadata records ``fallback: True``.
"""

from __future__ import annotations

import logging
import time
from operator import add
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .runner import DEFAULT_SYSTEM_PROMPT, SkillResult, render_prompt, run_atom
from .schema import SkillMeta

__all__ = ["MoleculeState", "build_molecule_graph", "run_molecule", "STEP_TITLES"]

logger = logging.getLogger("edu-agent.skills.molecule")

#: Resolver: atom skill name -> SkillMeta (None = unknown step).
SkillResolver = Callable[[str], "SkillMeta | None"]

#: Chinese section titles for well-known steps (fallback: the skill id itself).
STEP_TITLES = {
    "hint-generate": "分级提示",
    "concept-explain": "概念讲解",
    "knowledge-check": "理解检测",
}


class MoleculeState(TypedDict):
    """State flowing through the compiled molecule subgraph.

    ``context`` is the frozen per-request template context shared by all steps
    (steps only read it). ``system_prompt`` and ``llm`` are per-invoke values —
    they intentionally live in state, not in node closures, so a cached graph
    can serve any request. ``step_outputs`` accumulates via the ``add`` reducer.
    """

    context: dict
    system_prompt: str
    llm: Any
    step_outputs: Annotated[list, add]
    current_index: int


# ── default resolver (own catalog; skills package stays engine-agnostic) ──

_default_catalog: Any = None


def _default_resolver(name: str) -> SkillMeta | None:
    """Resolve atom ids against a lazily-built catalog of the skills/ tree."""
    global _default_catalog
    if _default_catalog is None:
        from .loader import SkillLoader
        from .catalog import SkillCatalog

        _default_catalog = SkillCatalog(SkillLoader().load_directory())
    return _default_catalog.get(name)


# ── graph builder ──────────────────────────────────────────────────


def _make_step_node(atom_skill: SkillMeta):
    """Build the LangGraph node function for one molecule step.

    The closure captures only the (immutable) step skill metadata. Everything
    request-specific (template context, system prompt, llm) is read from
    ``MoleculeState`` at run time.
    """

    async def step_node(state: MoleculeState) -> dict[str, Any]:
        ctx = dict(state.get("context") or {})
        prior = state.get("step_outputs") or []
        if prior:
            ctx["previous_output"] = prior[-1]["output"]
            ctx["previous_outputs"] = [
                {"skill": p["skill"], "output": p["output"]} for p in prior
            ]

        t0 = time.monotonic()
        result = await run_atom(
            atom_skill,
            ctx,
            state["llm"],
            system_prompt=state.get("system_prompt") or None,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "molecule step %r done (chars=%d elapsed_ms=%d)",
            atom_skill.name, len(result.output), elapsed_ms,
        )
        return {
            "step_outputs": [
                {
                    "skill": atom_skill.name,
                    "output": result.output,
                    "comprehension": result.comprehension,
                    "knowledge_delta": result.knowledge_delta,
                    "elapsed_ms": elapsed_ms,
                    "prompt_chars": result.metadata.get("prompt_chars", 0),
                }
            ],
            "current_index": (state.get("current_index", 0) + 1),
        }

    return step_node


def build_molecule_graph(
    skill: SkillMeta,
    resolver: SkillResolver,
) -> Any:
    """Compile a linear subgraph: one node per resolvable step of ``skill``.

    Steps whose id cannot be resolved from the catalog are skipped with a
    warning (the molecule still runs its remaining steps).
    """
    graph: StateGraph = StateGraph(MoleculeState)

    node_names: list[str] = []
    for i, step_id in enumerate(skill.steps):
        atom = resolver(step_id)
        if atom is None:
            logger.warning(
                "molecule %r: step %r not found in catalog — skipped",
                skill.name, step_id,
            )
            continue
        name = f"step_{i}_{step_id}"
        graph.add_node(name, _make_step_node(atom))
        node_names.append(name)

    if not node_names:
        # Empty graph is invalid in LangGraph; caller checks steps first and
        # falls back to run_atom, so this should never compile.
        raise ValueError(f"molecule {skill.name!r} has no resolvable steps")

    graph.add_edge(START, node_names[0])
    for src, dst in zip(node_names, node_names[1:]):
        graph.add_edge(src, dst)
    graph.add_edge(node_names[-1], END)

    return graph.compile()


# ── graph cache (topology-keyed; CPython dict ops are atomic) ──────

_graph_cache: dict[tuple, Any] = {}


def _get_graph(skill: SkillMeta, resolver: SkillResolver) -> Any:
    key = (skill.name, tuple(skill.steps))
    graph = _graph_cache.get(key)
    if graph is None:
        graph = build_molecule_graph(skill, resolver)
        _graph_cache[key] = graph
        logger.info(
            "compiled molecule subgraph %r (%d steps, cached)",
            skill.name, len(skill.steps),
        )
    else:
        logger.debug("molecule subgraph %r cache hit", skill.name)
    return graph


# ── entry point (called via runner.run_molecule) ───────────────────


async def run_molecule(
    skill: SkillMeta,
    state: dict[str, Any],
    llm: Any,
    *,
    system_prompt: str | None = None,
    resolver: SkillResolver | None = None,
) -> SkillResult:
    """Expand ``skill.steps`` into a linear subgraph and run it.

    Falls back to a single :func:`run_atom` call when no step resolves.
    """
    resolve = resolver or _default_resolver

    resolvable = [s for s in skill.steps if resolve(s) is not None]
    if not resolvable:
        logger.info(
            "molecule %r has no resolvable steps — falling back to atom run",
            skill.name,
        )
        result = await run_atom(skill, state, llm, system_prompt=system_prompt)
        result.metadata["fallback"] = True
        return result

    # The molecule body (persona/protocol) becomes each step's system prompt.
    if system_prompt:
        mol_system = system_prompt
    else:
        rendered = render_prompt(skill, state)
        mol_system = rendered if rendered.strip() else DEFAULT_SYSTEM_PROMPT

    graph = _get_graph(skill, resolve)
    final = await graph.ainvoke(
        {
            "context": dict(state),
            "system_prompt": mol_system,
            "llm": llm,
            "step_outputs": [],
            "current_index": 0,
        }
    )

    outputs = final.get("step_outputs") or []
    sections = []
    for i, out in enumerate(outputs):
        title = STEP_TITLES.get(out["skill"], out["skill"])
        sections.append(f"### 第 {i + 1} 步 · {title}\n\n{out['output']}")

    merged_delta: dict[str, Any] = {}
    for out in outputs:
        merged_delta.update(out.get("knowledge_delta") or {})

    last = outputs[-1]
    return SkillResult(
        output="\n\n---\n\n".join(sections),
        comprehension=last.get("comprehension", ""),
        knowledge_delta=merged_delta,
        metadata={
            "skill_id": skill.name,
            "skill_name": skill.name,
            "steps": [
                {
                    "skill": o["skill"],
                    "elapsed_ms": o.get("elapsed_ms"),
                    "prompt_chars": o.get("prompt_chars"),
                }
                for o in outputs
            ],
            "fallback": False,
        },
    )
