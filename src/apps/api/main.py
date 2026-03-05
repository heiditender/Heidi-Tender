from __future__ import annotations

import logging

from fastapi import FastAPI

from apps.api.core.config import get_settings
from apps.api.core.logging import setup_logging
from apps.api.routers import admin, chat, notices
from apps.api.services.indexing.qdrant_client import ensure_collection

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.2.0")


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting %s env=%s", settings.app_name, settings.app_env)
    try:
        ensure_collection()
    except Exception as exc:
        logger.warning("Qdrant init failed at startup: %s", exc)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(notices.router)
