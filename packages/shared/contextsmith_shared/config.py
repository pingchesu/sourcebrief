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

    model_config = SettingsConfigDict(env_prefix="CONTEXTSMITH_", extra="ignore")


def get_settings() -> Settings:
    return Settings()
