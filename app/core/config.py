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
    claude_model: str = ""  # global default (overridden by per-type settings below)
    research_model: str = "sonnet"
    builder_model: str = "opus"
    research_timeout_seconds: int = 1800
    builder_timeout_seconds: int = 1200

    # Workspace cleanup
    workspace_retention_hours: int = 72

    # Trading engine
    trading_engine_url: str = "http://arlo-trading-engine-api-1:8000"
    trading_engine_api_key: str = "arlo-trading-dev-key"
    trading_timeout_seconds: int = 3600

    # n8n
    n8n_base_url: str = "http://n8n:5678"
    n8n_api_key: str = "arlo-n8n-dev-key"
    n8n_poll_interval_seconds: int = 5
    n8n_execution_timeout_seconds: int = 600

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
