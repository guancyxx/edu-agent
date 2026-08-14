edu-agent/
├── backend/                    # FastAPI + LangGraph 后端
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI app 入口
│   │   ├── config.py           # Pydantic Settings
│   │   ├── database.py         # SQLAlchemy async engine
│   │   ├── deps.py             # FastAPI 依赖注入
│   │   │
│   │   ├── engine/             # LangGraph 引擎层
│   │   │   ├── __init__.py
│   │   │   ├── state.py        # TutorState TypedDict
│   │   │   ├── graph.py        # StateGraph 定义 + 编译
│   │   │   ├── nodes.py        # assess / router / execute / observe / update
│   │   │   └── llm.py          # ChatOpenAI (DeepSeek) 实例
│   │   │
│   │   ├── skills/             # Skill 运行时（加载 + 执行）
│   │   │   ├── __init__.py
│   │   │   ├── loader.py       # SkillLoader: frontmatter 解析 + 自动发现
│   │   │   ├── catalog.py      # SkillCatalog: 索引 + 按 profile 查询
│   │   │   ├── runner.py       # 执行 atom / molecule / compound
│   │   │   └── schema.py       # SkillMeta dataclass
│   │   │
│   │   ├── curriculum/         # 课标知识树
│   │   │   ├── __init__.py
│   │   │   ├── index.py        # CurriculumIndex: 加载 YAML + 查询知识点
│   │   │   └── data/
│   │   │       ├── math-grade-7.yaml
│   │   │       └── math-grade-8.yaml
│   │   │
│   │   ├── profile/            # 学生画像
│   │   │   ├── __init__.py
│   │   │   ├── models.py       # StudentProfile dataclass
│   │   │   ├── store.py        # PostgreSQL 读写
│   │   │   └── knowledge.py    # 知识掌握度图（邻接表 + mastery score）
│   │   │
│   │   ├── models/             # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── user.py         # User / Student / Parent / Teacher
│   │   │   ├── session.py      # ChatSession
│   │   │   └── event.py        # TeachingEvent 日志
│   │   │
│   │   ├── routers/            # FastAPI routes
│   │   │   ├── __init__.py
│   │   │   ├── auth.py         # 注册 / 登录 / JWT
│   │   │   ├── chat.py         # POST /chat (HTTP) + WebSocket
│   │   │   ├── profile.py      # 学生画像查询
│   │   │   ├── curriculum.py   # 课标查询
│   │   │   └── health.py       # 健康检查
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── auth.py         # JWT 工具
│   │
│   ├── alembic/                # 数据库迁移
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
│
├── skills/                     # Skill 文件（教学内容，不是代码）
│   ├── atoms/
│   │   ├── concept-explain.md
│   │   ├── hint-generate.md
│   │   ├── knowledge-check.md
│   │   ├── mistake-analyze.md
│   │   └── emotion-respond.md
│   ├── molecules/
│   │   ├── guided-solve.md
│   │   └── knowledge-gap-fill.md
│   ├── compounds/
│   │   └── training-session.yaml
│   ├── domains/
│   │   ├── math/
│   │   │   ├── algebra-basics.md
│   │   │   └── geometry-intro.md
│   │   └── english/
│   │       └── vocabulary.md
│   └── meta/
│       ├── skill-selector.md
│       └── student-assess.md
│
├── frontend/                   # Vue 3 + Capacitor
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.ts
│   │   ├── router/
│   │   ├── stores/             # Pinia
│   │   ├── composables/        # useChat, useAuth, useProfile
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   ├── profile/
│   │   │   └── common/
│   │   ├── views/
│   │   │   ├── ChatView.vue
│   │   │   ├── ProfileView.vue
│   │   │   ├── LoginView.vue
│   │   │   └── ParentDashboard.vue
│   │   └── assets/
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── capacitor.config.ts
│
├── docker/
│   └── docker-compose.yml
│
├── docs/
│   ├── ARCHITECTURE.md
│   └── SKILL-FORMAT.md
│
├── .gitignore
└── README.md
