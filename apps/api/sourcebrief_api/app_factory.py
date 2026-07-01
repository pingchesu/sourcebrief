from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterable

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

StartupHandler = Callable[[], None]


def cors_origins() -> list[str]:
    raw = os.getenv("SOURCEBRIEF_CORS_ORIGINS", os.getenv("CONTEXTSMITH_CORS_ORIGINS"))
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    # Keep the packaged/demo web port and common local dev/e2e Next.js ports in
    # the default allow-list. Otherwise the first-source browser flow fails as a
    # CORS-only "Failed to fetch" even though the form submitted correctly.
    return [
        "http://localhost:13000",
        "http://127.0.0.1:13000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3105",
        "http://127.0.0.1:3105",
        "http://localhost:3205",
        "http://127.0.0.1:3205",
    ]


def run_migrations_if_requested() -> None:
    if os.getenv("SOURCEBRIEF_AUTO_MIGRATE", os.getenv("CONTEXTSMITH_AUTO_MIGRATE", "false")).lower() == "true":
        subprocess.run(["alembic", "upgrade", "head"], check=True)


def create_app(*, startup_handler: StartupHandler | None = None, routers: Iterable[APIRouter] = ()) -> FastAPI:
    app = FastAPI(title="SourceBrief API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in routers:
        app.include_router(router)
    if startup_handler is not None:
        app.on_event("startup")(startup_handler)
    return app
