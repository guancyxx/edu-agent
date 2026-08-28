# AGENTS.md — edu-agent

> 跨 agent 唯一事实源。CC（实现）、Codex（审计）、Hermes（调度）共同遵守。
> 本文件是索引不是百科：细节在 docs/ 按需读取。判据：删掉这行 agent 会不会犯错？不会就删。

## 项目一句话

K12 自适应学习 Agent 平台：LangGraph 教学推理循环 + FastAPI + Vue3/Capacitor 三端。
架构细节见 `docs/ARCHITECTURE.md`，V2 范围见 `docs/V2-SCOPE.md`。

## 常用命令

| 动作 | 命令 |
|---|---|
| 基础设施 | `docker compose up -d postgres redis`（本地 PG=5433） |
| 后端起 | `cd backend && uvicorn app.main:app --reload --port 8000` |
| 后端测 | `cd backend && pytest`（pytest.ini 在 backend/） |
| 前端起 | `cd frontend && npm run dev` |
| 前端测 | `cd frontend && npm run test` |

## 环境铁律

- 本地 PG 是 docker `edu-postgres:5433`（edu_agent 库），`.env` 指 5433，别改成 5432。
- PR 一律 base=main。
- 生成图片直接交 agent（glm-4v-flash 免费），错题本功能是必保项，别动它的 schema。

## 三 agent 契约（谁拿什么、还什么）

| 角色 | 输入（必读集） | 输出契约 |
|---|---|---|
| Hermes（调度） | Vikunja 任务卡 status/priority/labels | 决策队列、委派 brief |
| CC（实现） | 本文件 + 任务卡 + 相关文件路径 | PR + handoff 文件 |
| Codex（审计） | `git diff main...head` + 本文件 + 任务验收标准 | APPROVE/BLOCK + 分级问题清单 |

- 任务真相 = Vikunja（https://tasks.guancyxx.cn，协议见 Hermes 技能 devops/vikunja-tasks）。
  本仓不写任务文件；执行记录写任务卡 comments。
- 委派 brief 四段式（Hermes→CC/Codex 必须遵守）：
  1. 目标（一句话）
  2. 边界（明确不做什么）
  3. 输出契约（handoff 文件路径 + ≤10 行摘要 + JSON `{status, findings[], artifacts[], blockers[]}`）
  4. 验收标准（可执行判据，如 `pytest 全绿`）
- handoff 文件落 `.agents/plans/<task-id>.md`（gitignore），下游 agent 读文件，不转述对话。
- 审计只看 diff 与其直接依赖，禁止全仓扫描。

## 修改纪律

- 方案过审才写码；PR 合并 + Vikunja 任务卡 comment 总结才算 done。
- 改 schema 同步 executor 与相关 ffmpeg/迁移脚本。
- 历史执行记录只追加不覆盖。
