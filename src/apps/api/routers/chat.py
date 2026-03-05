from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.models.db import get_db_session
from apps.api.models.schemas import ChatRequest, ChatResponse
from apps.api.services.agent.orchestrator import run_chat

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db_session)):
    response = run_chat(db, request)
    logger.info("Chat completed citations=%s", len(response.citations))
    return response
