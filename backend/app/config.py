from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout: int = 60

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/edu_agent"
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 1440

    # LangSmith
    langsmith_api_key: str = ""
    langsmith_project: str = "edu-agent"

    # Skills
    skills_dir: str = "../skills"

    # Feature flags
    use_langgraph: bool = True

    class Config:
        env_file = ".env"
        env_prefix = "EDU_"


settings = Settings()
