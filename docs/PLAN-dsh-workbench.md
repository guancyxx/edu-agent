# DSH Student Workbench — 双轨方案与实施计划

Status: DRAFT v1 (2026-08-14)
Owner: guancyxx
Related: docs/ARCHITECTURE.md (LangGraph 主线), ShuJieTai「接基座不造基座」原则

## 1. 背景与定位

两条轨道并行，互补而非竞争：

| 轨道 | 引擎 | 场景 | 状态 |
|------|------|------|------|
| 1. LangGraph 教学引擎 | 自研（backend/app/engine） | 确定性教学循环：assess→router→execute→observe→update、错题本 SM-2、多角色 | 已端到端跑通，主线不动 |
| 2. DSH 学生工作台 | deepseek-harness (dsh) | 学生自由探索 + 编程实践，agent 基座可换 | 本文档，实验线 |

教学数据（课标树、画像、错题、复习计划）single source of truth 永远在 edu-agent FastAPI 后端。dsh 只做 agent 基座和交互壳，通过插件调我们的 API。

## 2. 为什么是 dsh

- Everything is a Plugin（Cordis）：加模型工具 ~20 行 TS（ctx.tools.register + defineTool）
- per-session agent presets + permission presets：可做「禁 bash/editor、只有教学工具」的 student preset
- SKILL.md 格式与 edu-agent skills/ 目录同构，可平移
- 自定义 OpenAI 兼容 provider：可指向自建网关（配额/计费/模型路由），vision 模型可在 settings.yaml 声明 input: [text, image]
- Typert interceptor 在 API Proxy 之前拦截所有 RPC —— 官方预留的认证劫持点

风险：developer preview，会 breaking change。对冲：教学逻辑全在后端 + 薄插件层，dsh 可整体替换。

## 3. 认证与会话隔离设计（用户确认的简化方案）

dsh 自身无认证（官方明示：No TLS, auth, or origin policy）。方案：两个插件职责，隔离逻辑走常规接口层。

### 3.1 登录闸（edu-auth-plugin）

1. `ctx.webServer.register({ path: '/workbench' })`：登录入口，跳转 edu-agent 后端 JWT 登录（或嵌登录页）
2. Typert interceptor 拦截全部 Remote endpoint：无有效 JWT → 401，UI 与 RPC 双断
3. 登录成功后 token 保存在 host 侧（绑定 connection/session），供后续接口层使用

### 3.2 会话隔离（接口层常规逻辑）

- `session.create` 拦截：往会话元数据盖 `owner: user_id`
- `session.list` / 读取类端点：按 owner 过滤，学生 A 永远看不到学生 B
- 隔离逻辑集中在这一个 interceptor 薄层，dsh 本体零改动

### 3.3 token 透传给工具层

- edu 工具插件执行时携带当前学生 JWT 调 FastAPI：query_mistakes / get_curriculum / submit_answer 等
- 后端按 JWT 里的 user_id 做数据隔离（与现有 LangGraph 路由同一套逻辑）

### 3.4 实施中验证的架构事实（T1/T5 实测）

- **组合即限制（无 deny 语法）**：dsh Web host 组合（packages/bundle/web-app/cordis.patch.yml）默认 `disabled: true` 所有模型工具行（tool-bash/tool-fs/tool-str-replace-editor/tool-web/...）。preset 是会话的完整 agent 平面组合——**不挂某行 = 该工具不存在**。student preset 无需任何 deny 配置，已实测验证：模型自述唯一可用工具为白名单项。
- **preset 分发只能走 DSH_HOME**：`--patch` 无法注入 preset 根——CLI profile-boot（apps/cli/src/profile-boot.ts:159-167）强制覆盖 `agent-presets.roots` 为内置根。自定义 preset 必须放 `$DSH_HOME/.agent-presets/`。影响部署：学生工作台的 preset 需随容器镜像/启动脚本预置。
- `ctx.tools.restrict({allow/deny})` 存在但是 TS API（preset YAML 用不了），且官方明言「visibility composition, not an authority boundary」。
- persona 用 `complete: true` + `includeRuntimeContext: false`：系统提示完全自持（全局段无法注入文本）、不泄露宿主路径。
- 用户级 preset = shell 级信任；生产环境 student preset 应以 system root 下发，且 interceptor 应阻断 `agentPreset.copy/openDocument`（防学生读取/复制组合探查能力面）。

### 3.5 残余边角（实现时验证）

- settings/credentials 特权端点被钉死 loopback：反代进来的学生不可达（符合预期），但要确认 web UI 不因此白屏；模型部署侧预配
- workspace 是进程级共享：student preset 禁 bash/editor，或按学生子目录 + fs 策略
- 扩展：单 host 单班试点；上量按每容器一 host 横向切

## 4. 架构图

```
[Student Browser]
   │ JWT (edu-agent 后端签发)
   ▼
[Nginx/Caddy 反代] ──验 JWT──► [edu-agent FastAPI] ◄──教学数据 API──┐
   ▼ trustedHosts                  ▲ user_id 隔离                   │
[dsh host (loopback)]              │ JWT 透传                       │
   ├─ edu-auth-plugin (登录闸+owner 盖章)                            │
   ├─ edu-tools-plugin (教学工具──┘)                                │
   ├─ student preset (禁 shell/editor, 只留教学工具)                 │
   ├─ skills/ (从 edu-agent skills 平移)                            │
   └─ custom provider → 自建 OpenAI 兼容网关 (配额/模型路由)  ◄───────┘
```

## 5. 代码位置

`edu-agent/dsh-workbench/` —— 独立子目录（将来可拆库），含：
- `plugins/edu-auth/` 登录闸 + interceptor
- `plugins/edu-tools/` 教学工具集
- `presets/student.cordis.yml` 学生预设
- `gateway/` 网关雏形（可选 Phase 1）
- `spike/` 验证脚本

## 6. 任务分解

| # | 任务 | 执行者 | 验收 | 状态 |
|---|------|--------|------|------|
| T0 | 本方案文档 | Hermes | 本文件 | ✅ |
| T1 | dsh 插件开发环境 spike | Codex+Hermes | greet 工具被模型真实调用（Hello, Ada!） | ✅ |
| T2 | edu-auth-plugin 登录闸 | Codex+Hermes | 无 token /api → 401 + www-authenticate；/workbench 200 | ✅ |
| T3 | owner 盖章 + 会话过滤 | Codex+Hermes | 双学生 isolation PASS（sidecar 持久，fail-closed） | ✅ |
| T4 | edu-tools-plugin 3 教学工具 | Codex+Hermes | 三工具真数据全链路，submit_answer 201 入库 SM-2 字段齐全 | ✅ |
| T5 | student preset | Codex+Hermes | 模型自述唯一工具为白名单项（组合即限制） | ✅ |
| T6 | custom provider 网关 | — | 延后：模型 key 已在部署侧预配，网关是加投阶段需求 | ⏸ |
| T7 | 端到端双学生验收 | Hermes | 四项全 PASS（401 闸/隔离/后端数据/入口页） | ✅ |

规则：每任务独立 commit/分支；并发 ≤3；额度用尽（Codex quota/auth 报错）→ 停下报告，不降级为 Hermes 手写。

## 7. Phase 划分

- Phase 0（1 周）：T1–T5，本地单机验证
- Phase 1：T6–T7 + Python SDK 服务端池化评估（如需多 host）
- Phase 2：观察 dsh 稳定性（1.0/API 冻结信号），决定加投或换基座
