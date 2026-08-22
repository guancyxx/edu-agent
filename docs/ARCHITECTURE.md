# EduAgent Architecture

> 这份文档写的是**当前架构**。CDUT v2 原始方案（`cdut_stu_agents@2c0817b`）里还剩多少有效、
> 哪些已作废、剩余投入怎么分桶，见 [V2-SCOPE.md](V2-SCOPE.md) —— 排期以那份为准。

## Overview

EduAgent uses **LangGraph** as the core agent engine for K12 adaptive tutoring.

```
Student Message (WebSocket)
     │
     ▼
┌──────────────────────────────────────────────────┐
│              LangGraph StateGraph                  │
│                                                    │
│  START → assess → router → execute → observe       │
│                       ▲                │           │
│                       │               ▼            │
│                       └──────── update ────► END   │
│                                                    │
│  (conditional: observe → router if continue)       │
└──────────────────────────────────────────────────┘
```

## Core Concepts

### 1. TutorState

A `TypedDict` that flows through every node. Contains:
- `messages`: conversation history (LangGraph `add` reducer)
- Student profile: `knowledge_mastery`, `emotion_state`, `ability_level`, `learning_style`
- Turn decision: `selected_skill`, `skill_params`, `skill_layer`
- Execution result: `skill_output`, `comprehension_signal`, `knowledge_delta`
- Control flow: `should_continue`, `iteration_count`

### 2. Five Nodes

| Node | Input | Output | LLM Call |
|------|-------|--------|----------|
| **assess** | student_id | Profile fields loaded into state | 0 |
| **router** | message + profile + skill catalog | selected_skill, skill_params | 1 (skill-selector) |
| **execute** | selected_skill + params | skill_output, comprehension_signal | 1 (skill LLM call) |
| **observe** | comprehension + iteration | should_continue bool | 0 |
| **update** | knowledge_delta + outcome | Profile + teaching log updated | 0 |

Total: **2 LLM calls per turn** (vs CDUT v1's 3 calls).

### 3. Skill System

Three-layer structure (inspired by MagicEdit Skill Graphs 2.0):

```
skills/
├── atoms/        # Single-step teaching actions (LLM call = 1)
├── molecules/    # Multi-step teaching flows (LLM calls = N)
├── compounds/    # Full lesson units (DAG of molecules)
├── domains/      # Subject-specific skills (math/, english/, ...)
└── meta/         # System skills (router, assessment)
```

Each skill is a `.md` file with YAML frontmatter:
- Metadata: name, layer, category, version, status
- Triggers: when to use this skill
- Inputs/Outputs: structured contract
- Body: Jinja2 prompt template rendered with TutorState

### 4. Curriculum Knowledge Tree

YAML files mapping the Chinese K12 curriculum standard:

```
curriculum/data/
├── math-grade-7.yaml    # 4 chapters, 16 knowledge points
├── math-grade-8.yaml    # 5 chapters, 18 knowledge points
└── ...
```

Each knowledge point has:
- `id`: curriculum-standard ID (e.g., "7-1-3")
- `prerequisites`: list of KP IDs that must be mastered first
- `difficulty`: 1-5 scale

Skills reference KP IDs via `triggers.knowledge_point`. After execution, `knowledge_delta` updates mastery scores.

### 5. Multi-Role Support

The `role` field in TutorState (student/parent/teacher) changes:
- Which skills are available (router selects different skills)
- How information is presented (student gets tutoring, parent gets reports)
- What actions are allowed (teacher can assign homework)

### 6. Adaptive Evolution

Three levels of self-improvement:

**Level 1 (Daily)**: LangSmith traces show which skills have low comprehension rates → prompt A/B test → promote better version.

**Level 2 (Weekly)**: Router decision accuracy analysis → optimize skill-selector prompt → regression test against historical traces.

**Level 3 (Monthly)**: Discover uncovered teaching scenarios → create new skills → restructure existing ones.

## Persistence

| Store | What | How |
|-------|------|-----|
| PostgreSQL | User profiles, chat sessions, teaching events | SQLAlchemy async |
| PostgreSQL | LangGraph checkpoints | PostgresSaver (auto-managed) |
| Redis | Session cache, rate limiting | redis-py async |

## Frontend (Three-Device Strategy)

```
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│  Phone App  │  │  Tablet/PWA  │  │  Desktop     │
│  Capacitor  │  │  Vue 3 PWA   │  │  Tauri (future)│
│             │  │              │  │              │
│ - Push notif│  │ - Full UI    │  │ - Multi-panel│
│ - Camera    │  │ - Touch +    │  │ - Keyboard   │
│ - Offline   │  │   handwriting│  │   shortcuts  │
└──────┬──────┘  └──────┬───────┘  └──────┬───────┘
       └────────────────┼─────────────────┘
                        │
                 FastAPI + WebSocket
```

All three share one Vue 3 codebase. Capacitor wraps the PWA into native iOS/Android apps with access to device APIs (camera, push notifications, offline storage).
