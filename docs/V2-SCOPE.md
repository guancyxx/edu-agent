# V2 方案存量盘点（CDUT v2 → edu-agent）

> 原文：`cdut_stu_agents@2c0817b` 的 `docs/PLAN-v2-langgraph.md`（643 行）+ `docs/PLAN-v2-adaptive-agent.md`（526 行）。
> 原文不复制到本仓，要看跑 `git -C ~/workspace/cdut_stu_agents show 2c0817b:docs/PLAN-v2-langgraph.md`。
>
> **这份文档解决什么**：v2 已确认走 edu-agent 独立仓，CDUT 老仓转维护。两份原文写于 2026-08-14
> （edu-agent 建仓当天），此后一周主干功能基本被实现掉，同时学科面从「竞赛/OJ 算法教练」换成了
> 「K12 学科辅导」。原文因此既不能当施工图，也不能直接扔。本文逐条标注它还剩多少有效，
> 并把剩余投入分成三桶。**看这一份就够，不用再回去读原文。**
>
> 状态图例：✅ 已实现 · ⚠️ 部分实现/有缺口 · ❌ 未做 · 🗑️ 作废

---

## 1. PLAN-v2-langgraph.md 逐条标注

| 原文章节 | 结论 | 说明 |
|---|---|---|
| §1 推翻手写引擎，选 LangGraph | ✅ | 决策成立并已落地，LangGraph 是现实基座。本节归档，不再讨论。 |
| §2 架构总览（五节点图） | ✅ | 见 `backend/app/engine/graph.py`。 |
| §3.1 `TutorState` TypedDict | ✅ | `backend/app/engine/state.py`。字段比原文多：`subject` / `grade` / `role`（K12 多学科 + 多角色带来的）。 |
| §3.2 五节点定义 | ✅ | `backend/app/engine/nodes.py`。情绪短路按原文 `frustration > 0.7` 实现，另加了 `confusion > 0.8`。原文的独立 `emotion_analyzer` 已按 §6.1 的处置合并进 `assess_node`。 |
| §3.3 图组装 + `PostgresSaver` | ⚠️ | 图已装（含 `observe → router` 条件回边）。**checkpointer 是 `MemorySaver`，不是 `PostgresSaver`** —— 进程重启即丢会话状态。依赖 `langgraph-checkpoint-postgres` 已在 `requirements.txt`，装了没用。→ **A1** |
| §4.1 molecule = LangGraph subgraph | ⚠️ | molecule 层存在且可路由到（`skills/molecules/guided-solve.md`），但 `runner.run_molecule` 内部直接 delegate 给 `run_atom`（注释写着 `subgraph pending`）—— **多步教学流程被拍平成单次 LLM 调用**，`steps: [hint-generate, concept-explain, knowledge-check]` 这个编排没有真正执行。→ **A2** |
| §4.2 atom = prompt 模板 | ✅ | `skills/loader.py` + `runner.render_prompt`（Jinja2）。 |
| §4.3 compound = 嵌套子图 + `interrupt()` | ❌ | `skills/compounds/` 目录不存在，`interrupt()` 零使用。`runner.run()` 对 compound 直接抛 `NotImplementedError`。→ **B1** |
| §5.1 LangSmith 集成 | ❌ | `config.py` 有 `langsmith_api_key` / `langsmith_project` 字段，**代码零接入**（没有设 `LANGCHAIN_TRACING_V2`）。→ **B2** |
| §5.2 prompt 进化闭环（evaluate + A/B） | ❌ | 未开始。依赖 B2 先有 trace。→ **B3** |
| §5.3 三层进化（日/周/月级） | ❌ | 同上，是 B2/B3 之上的运营节奏，不是代码任务。 |
| §6.1 v1 文件对照表（14 个文件的处置） | 🗑️ | 新仓建仓即是 v2，没有 `supervisor.py` / `workers/` 可迁。整表作废。 |
| §6.2 渐进迁移 + feature flag 灰度 | 🗑️ | 同上。`USE_LANGGRAPH` flag 仍在 `config.py` 且默认 `true`，但**没有旧引擎可回退**，它现在是个空开关（留着无害，别当它是保险）。 |
| §7 技术栈变更（依赖 + ChatOpenAI + 持久化） | ✅ | `requirements.txt` 依赖齐全；`engine/llm.py` 用 `ChatOpenAI` 指向 DeepSeek。持久化部分见 A1。 |
| §8 路线图 Phase 0 / Phase 1 | ✅ | 除 checkpointer（A1）和 LangSmith（B2）外全部完成。 |
| §8 路线图 Phase 2 | ⚠️ | atom 补齐 4 个（原文要 10 个，但要的是竞赛题面，见下）；molecule 1 个（拍平中）；compound / HITL / trace 可视化未做。 |
| §8 路线图 Phase 3 / Phase 4 | ❌ | 未开始。Phase 4 里「知识图谱可视化 / 学习路径生成 / 代码沙箱 / 多模态」需按 K12 重写，不能照搬。 |
| §9 两方案对比表 / §10 推荐方案 B | 🗑️ | 决策已做完，归档价值 > 参考价值。 |
| §11 快速验证（跑通 CodeReviewer skill） | 🗑️ | 学科面已变，没有 CodeReviewer。验证早已由真实 K12 对话链路取代。 |

---

## 2. PLAN-v2-adaptive-agent.md 逐条标注

| 原文章节 | 结论 | 说明 |
|---|---|---|
| §1 v1 现状与六个核心问题 | 🗑️ | 描述的是 CDUT v1（Supervisor + 5 Worker）。纯历史，归档。 |
| §2 目标架构 / TutorLoop ReAct 循环 | 🗑️ | 被 LangGraph StateGraph 等价取代（这正是 langgraph 那份文档 §1 的论点）。「教育版 ReAct」这个手写引擎不再存在。 |
| §3.1 skill 三层目录结构 | ⚠️ | 目录形态 ✅（`atoms/` `molecules/` `domains/` `meta/`，缺 `compounds/`）。**内容全换**：原文列的是 dp / graph / string / math(数论组合) 竞赛知识域，现状是 `domains/math/`（代数、几何入门）+ `domains/english/`（词汇）。 |
| §3.2 skill 文件格式（YAML frontmatter） | ✅ | `skills/schema.py` + `loader.py` 已实现 name/layer/category/version/status/triggers/inputs/outputs。原文的 `metrics` 字段未实现（依赖 B2/B3 才有意义）。 |
| §3.3 compound YAML DAG | ❌ | 未做，见 B1。注意原文这里用的是独立 YAML 文件格式，若做建议直接用 LangGraph subgraph 代码定义，不再引入第二套 DAG 描述格式。 |
| §4 TutorLoop 引擎伪代码 | 🗑️ | 同 §2。 |
| §5.1 三层进化 | ❌ | 见 B3。 |
| §5.2 `teaching_events` 表 | ⚠️ | 表已建（`TeachingEventDB`）且 `routers/chat.py` 每轮写入 skill_id / student_message / skill_output / comprehension / iteration_count。**缺原文设计的反馈字段**：`comprehension_rating`、`helpfulness_rating`、`followup_correct_rate`、`time_to_solve_sec` —— 也就是说现在只有系统自评，没有学生反馈。→ **B3** |
| §5.2 `skill_ab_tests` 表 | 🗑️ | 不自己建表。LangSmith 的 experiment / evaluate 覆盖同样场景，自建等于重造一遍还没有 UI。 |
| §6 学生画像 `StudentProfile` | ⚠️ | `profile/models.py` 实现了 `knowledge_mastery` / `emotion_history` / `learning_style` / `recent_mistakes`。**未实现**：`ability_scores` 多维能力（code_speed/debugging/algorithm_design —— 这三个维度本身也是竞赛面的，K12 要重新定义）、`learning_patterns`。 |
| §7 路线图 Phase 0-4 | — | 与 langgraph 文档 §8 重复，以 §8 为准。 |
| §8 从 MagicEdit 借鉴的 9 个模式 | ⚠️ | 三层 skill ✅、frontmatter ✅、loader 自动发现 ✅、per-skill 上下文注入 ✅；HITL checkpoint ❌（B1）；A/B ❌（B3）；**`commit_*` 信号工具 🗑️** —— 那是 Node 手写 ReAct 里做确定性交接用的，LangGraph 下节点和边本身就是确定性交接，不需要。 |
| §9 不从 MagicEdit 借鉴的部分 | ✅ | 判断依然成立（无画布、单学生单会话无并发锁需求）。唯一变化：原文说「固定用 DeepSeek，不需要 model routing」，现状已是**双 provider**（DeepSeek 文本 + 智谱 GLM 视觉），见下。 |
| §10 技术栈 | ⚠️ | FastAPI + PostgreSQL + Redis + Vue3 + Docker 不变。**新增原文没有的**：视觉模型 `glm-4v-flash`（图片直接交 agent）、Capacitor 三端。 |
| §11 快速验证（CodeReviewer prompt → skill 文件） | 🗑️ | 同 langgraph §11。 |

---

## 3. 两份文档没覆盖的（现状有、原文无）

写于建仓当天，这些都是之后长出来的，**不在原文任何章节里，别去原文找**：

- **错题本 + SM-2 间隔重复** —— `MistakeEntryDB` + `spaced_repetition/` + 前端复习页。`update_node` 在 comprehension 为 confused/partial 时自动落错题。这是 K12 场景的核心功能，竞赛面文档里完全没有对应物。
- **多角色**（student / parent / teacher）—— `User.role` + `TutorState.role`，影响可用 skill 与呈现方式。
- **curriculum 知识树** —— `curriculum/index.py` + `math-grade-7/8.yaml`（含 `prerequisites` / `difficulty`）。⚠️ **目前是孤岛：engine 里零引用**，知识点 ↔ skill ↔ 掌握度这条锚没接上。原文 §5 的「知识图谱锚定」原则对应的就是这件事，但原文是竞赛知识图谱，实现是 K12 课标树。→ **A3**
- **dsh 学生工作台线** —— 见下节。
- **视觉输入** —— GLM `glm-4v-flash`。明确**不做拍照搜题**，图片直接交给 agent 理解。

---

## 4. dsh 工作台线与主线的关系

两份原文完全没提，因为它是 08-14 之后才立的第二条线。定位：

```
主线（本仓 backend/ + frontend/）        dsh 实验线（本仓 dsh-workbench/）
自研 LangGraph 产品                      deepseek-harness 插件系统改造的学生工作台
FastAPI + Vue3 + Capacitor 三端           dsh 作 agent 基座
        │                                        │
        └────── 教学数据源（FastAPI /api）────────┘
```

- **agent 基座是 dsh，教学信息来自 edu-agent 后端** —— 三个插件（`edu-auth` / `edu-session-owner` / `edu-tools`）里，`edu-tools` 的 `query_mistakes` / `get_curriculum` / `submit_answer` 全部回调本仓 FastAPI。
- 认证：登录闸 + JWT（HS256，`EDU_SECRET_KEY`）+ owner 盖章会话隔离，T8-T13 已全部验证通过，详见 `docs/PLAN-dsh-workbench.md` 与 `dsh-workbench/DEPLOY.md`。
- **对本文档的意义**：v2 原文的「前端适配」类条目（Phase 2 的 skill 执行进度 UI、Phase 3 的学生反馈收集 UI）现在有两个落点，做之前先定是落主线前端还是 dsh 工作台，别默认前者。

---

## 5. 剩余投入范围（三桶）

### A 桶 —— 收口，值得排

原文要求成立、现状不符、改动确定性高。三项彼此独立，可拆三个 PR。

| ID | 事项 | 现状 → 目标 | 参考 |
|---|---|---|---|
| **A1** | checkpointer 换 PostgresSaver | `MemorySaver` → `PostgresSaver`，会话跨重启存活 | langgraph §3.3 / §7 |
| **A2** | molecule 展开成真 subgraph | `run_molecule` 拍平成单次 atom 调用 → 按 frontmatter `steps` 编排子图 | langgraph §4.1 |
| **A3** | curriculum 接进 engine | 知识树孤岛 → `assess`/`router` 读知识点与 `prerequisites`，`knowledge_delta` 按 KP id 回写 | adaptive §3.1 的「知识图谱锚定」原则 |

### B 桶 —— 放着，等真实流量

不是不做，是现在做没有输入数据，做完也无从判断好坏。

| ID | 事项 | 解锁条件 |
|---|---|---|
| **B1** | compound + `interrupt()` 教学检查点 | 先有稳定的 molecule 编排（A2），且教学流程长到需要中途确认 |
| **B2** | LangSmith trace 接入 | 有真实学生会话量，否则 trace 里只有自测数据 |
| **B3** | 学生反馈字段 + skill 版本 A/B + prompt 进化 | 依赖 B2；并需补 `teaching_events` 的 rating 字段和前端打分入口 |

### C 桶 —— 作废，别再捡

| 事项 | 作废理由 |
|---|---|
| 竞赛/OJ 全部 domain skill（DP、图论、数据结构、字符串、数论） | 学科面已换成 K12 |
| code-review / complexity-analysis / edge-case-identify 等竞赛 atom | 同上 |
| contest-simulation / contest-prep-cycle 等竞赛 compound | 同上 |
| v1 文件对照表、v1/v2 共存、feature flag 灰度 | 新仓无 v1 可迁 |
| `skill_ab_tests` 表 | LangSmith evaluate 覆盖 |
| `commit_*` 信号工具 | LangGraph 的节点/边即确定性交接 |
| TutorLoop 手写 ReAct 引擎 | LangGraph 取代 |
| 两份文档的 §11 快速验证 PR | 早已被真实链路取代 |
| 拍照搜题 | 明确不做，图片直接交 agent |

---

## 6. 一句话结论

原文 1169 行里，**引擎骨架部分已经建完（不用再看）**，**竞赛学科面整体作废（约占篇幅一半）**，
真正剩下的是 A 桶三项收口 + B 桶三项等条件。后续排期以本文档 §5 为准，不再回原文取任务。
