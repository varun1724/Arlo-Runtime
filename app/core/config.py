from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Postgres
    database_url: str = "postgresql+asyncpg://arlo:arlo_dev_password@db:5432/arlo"

    # Auth
    arlo_auth_token: str = "change-me-to-a-real-secret"

    # Workspace
    workspace_root: str = "/workspaces"

    # Worker
    worker_poll_interval_seconds: int = 2

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Claude Code CLI
    claude_command: str = "claude"
    claude_model: str = ""
    research_timeout_seconds: int = 600
    builder_timeout_seconds: int = 900

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
