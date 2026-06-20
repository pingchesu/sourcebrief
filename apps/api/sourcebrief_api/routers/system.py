from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_session
from sourcebrief_shared.embeddings import verify_provider_health

router = APIRouter(tags=["system"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("select 1"))
    Redis.from_url(get_settings().redis_url).ping()
    return {"status": "ready"}


@router.get("/provider-health")
def provider_health() -> JSONResponse:
    health = verify_provider_health()
    status_code = 200 if health.get("status") == "ok" else 503
    return JSONResponse(status_code=status_code, content=health)
