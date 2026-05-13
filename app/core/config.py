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

    # Round 5: email notifications (async approval flow)
    # When approval_recipient_email is blank, notifications are a no-op.
    # This is the single opt-in switch for the whole notification system.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from_address: str = "arlo@localhost"
    approval_recipient_email: str = ""
    notification_base_url: str = "http://localhost:8000"

    # Per-pipeline opt-in for the polymarket-signals email digest.
    # When False (default), even brand-new high-edge signals don't email —
    # the user reads them in the iOS app. Set ARLO_POLYMARKET_NOTIFY_EMAIL=true
    # to re-enable per-cycle digests.
    polymarket_notify_email: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # ignore unrelated keys (e.g. docker-compose vars in .env)
    }


settings = Settings()
