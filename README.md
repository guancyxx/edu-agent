# EduAgent — K12 自适应学习 Agent 平台

> 基于 LangGraph 的多学科 AI 辅导系统，支持手机 / 平板 / 电脑三端

## 核心特性

- **LangGraph 引擎** — 状态图驱动的教学推理循环（assess → router → execute → observe → update）
- **三层 Skill 体系** — atom（单步教学）/ molecule（多步流程）/ compound（完整课程），.md 文件自动发现
- **多学科支持** — 数学 / 语文 / 英语 / 物理 / 化学 / 编程，按学科分 domain skill
- **课标对齐** — 中国 K12 课程标准知识树，每个 skill 关联知识点 ID
- **三端互联** — Vue 3 PWA + Capacitor 打包 iOS/Android，响应式布局适配平板
- **多角色** — 学生学习 / 家长看报告 / 教师管班级，同一 Agent 按角色切换行为
- **自适应进化** — LangSmith trace + evaluate 实现教学效果闭环，skill prompt 自动调优

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 引擎 | LangGraph + LangChain |
| 后端 | FastAPI + PostgreSQL + Redis |
| 前端 | Vue 3 + Vite + Pinia + Capacitor |
| LLM | DeepSeek API (OpenAI-compatible) |
| 可观测 | LangSmith |

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:guancyxx/edu-agent.git
cd edu-agent

# 2. 启动基础设施
docker compose up -d postgres redis

# 3. 后端
cd backend
cp .env.example .env  # 填入 DEEPSEEK_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 4. 前端
cd ../frontend
npm install
npm run dev
```

## 项目结构

```
edu-agent/
├── backend/           # FastAPI + LangGraph
├── skills/            # Skill 文件（教学内容）
│   ├── atoms/         # 原子教学动作
│   ├── molecules/     # 多步教学流程
│   ├── compounds/     # 完整教学单元
│   ├── domains/       # 学科专属 skill
│   └── meta/          # 元 skill（路由、评估）
├── frontend/          # Vue 3 + Capacitor
└── docker/            # Docker Compose
```

## 架构文档

- [架构设计](docs/ARCHITECTURE.md)
- [Skill 格式规范](docs/SKILL-FORMAT.md)

## License

MIT
