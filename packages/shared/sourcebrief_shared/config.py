import os

from pydantic import BaseModel, ConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://sourcebrief:sourcebrief@localhost:55432/sourcebrief"
DEFAULT_REDIS_URL = "redis://localhost:6380/0"


def _env(name: str, legacy: str | None = None, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    if legacy and legacy in os.environ:
        return os.environ[legacy]
    return default


def _env_bool(name: str, legacy: str | None = None, default: bool = False) -> bool:
    raw = _env(name, legacy, "true" if default else "false")
    return str(raw).lower() in {"1", "true", "yes", "on"}


def _renamed_default_env(name: str, legacy: str, *, old_default: str, new_default: str) -> str:
    value = os.environ.get(name)
    if value:
        return new_default if value == old_default else value
    legacy_value = os.environ.get(legacy)
    if legacy_value:
        return new_default if legacy_value == old_default else legacy_value
    return new_default


class Settings(BaseModel):
    # SOURCEBRIEF_* is canonical. CONTEXTSMITH_* remains a legacy alias for existing deployments.
    database_url: str
    redis_url: str
    auto_migrate: bool
    dev_auth: bool
    admin_email: str | None
    admin_password: str | None
    admin_display_name: str
    bootstrap_workspace_name: str
    bootstrap_workspace_slug: str
    bootstrap_project_name: str

    model_config = ConfigDict(extra="ignore")


def get_settings() -> Settings:
    """Build settings from the current environment.

    Environment is read at call time so tests and one-shot bootstrap jobs can
    override SOURCEBRIEF_* values without reloading the module. We avoid
    BaseSettings here because this module needs custom rename behavior: exact
    legacy branding defaults should become SourceBrief while custom legacy values
    remain respected.
    """
    return Settings(
        database_url=os.getenv("DATABASE_URL")
        or _env("SOURCEBRIEF_DATABASE_URL", "CONTEXTSMITH_DATABASE_URL", DEFAULT_DATABASE_URL)
        or DEFAULT_DATABASE_URL,
        redis_url=os.getenv("REDIS_URL")
        or _env("SOURCEBRIEF_REDIS_URL", "CONTEXTSMITH_REDIS_URL", DEFAULT_REDIS_URL)
        or DEFAULT_REDIS_URL,
        auto_migrate=_env_bool("SOURCEBRIEF_AUTO_MIGRATE", "CONTEXTSMITH_AUTO_MIGRATE"),
        dev_auth=_env_bool("SOURCEBRIEF_DEV_AUTH", "CONTEXTSMITH_DEV_AUTH"),
        admin_email=_env("SOURCEBRIEF_ADMIN_EMAIL", "CONTEXTSMITH_ADMIN_EMAIL"),
        admin_password=_env("SOURCEBRIEF_ADMIN_PASSWORD", "CONTEXTSMITH_ADMIN_PASSWORD"),
        admin_display_name=_renamed_default_env(
            "SOURCEBRIEF_ADMIN_DISPLAY_NAME",
            "CONTEXTSMITH_ADMIN_DISPLAY_NAME",
            old_default="ContextSmith Admin",
            new_default="SourceBrief Admin",
        ),
        bootstrap_workspace_name=_renamed_default_env(
            "SOURCEBRIEF_BOOTSTRAP_WORKSPACE_NAME",
            "CONTEXTSMITH_BOOTSTRAP_WORKSPACE_NAME",
            old_default="ContextSmith",
            new_default="SourceBrief",
        ),
        bootstrap_workspace_slug=_renamed_default_env(
            "SOURCEBRIEF_BOOTSTRAP_WORKSPACE_SLUG",
            "CONTEXTSMITH_BOOTSTRAP_WORKSPACE_SLUG",
            old_default="contextsmith",
            new_default="sourcebrief",
        ),
        bootstrap_project_name=_env(
            "SOURCEBRIEF_BOOTSTRAP_PROJECT_NAME",
            "CONTEXTSMITH_BOOTSTRAP_PROJECT_NAME",
            "Default Project",
        )
        or "Default Project",
    )
