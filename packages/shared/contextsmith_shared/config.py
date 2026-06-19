import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = os.getenv(
        "DATABASE_URL",
        os.getenv(
            "CONTEXTSMITH_DATABASE_URL",
            "postgresql+psycopg://contextsmith:contextsmith@localhost:55432/contextsmith",
        ),
    )
    redis_url: str = os.getenv(
        "REDIS_URL", os.getenv("CONTEXTSMITH_REDIS_URL", "redis://localhost:6380/0")
    )
    auto_migrate: bool = False
    dev_auth: bool = False
    admin_email: str | None = None
    admin_password: str | None = None
    admin_display_name: str = "ContextSmith Admin"
    bootstrap_workspace_name: str = "ContextSmith"
    bootstrap_workspace_slug: str = "contextsmith"
    bootstrap_project_name: str = "Default Project"

    model_config = SettingsConfigDict(env_prefix="CONTEXTSMITH_", extra="ignore")


def get_settings() -> Settings:
    return Settings()
