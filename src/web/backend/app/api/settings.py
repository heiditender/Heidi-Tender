from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth.dependencies import SessionUser, get_current_user
from ..config import Settings, get_settings
from ..db import get_db
from ..repositories.app_settings import AppSettingsRepository
from ..repositories.auth import AuthRepository
from ..schemas import ModelSettingsResponse, SetModelRequest
from ..services.auth import enforce_same_origin, get_request_ip, get_request_user_agent


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/model", response_model=ModelSettingsResponse)
def get_model_settings(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> ModelSettingsResponse:
    repo = AppSettingsRepository(db)
    model = repo.get_current_openai_model(
        default_model=settings.openai_model,
        allowed_models=settings.allowed_openai_models,
    )
    return ModelSettingsResponse(
        current_model=model,
        allowed_models=settings.allowed_openai_models,
        has_api_key=bool(settings.openai_api_key),
    )


@router.put("/model", response_model=ModelSettingsResponse)
def set_model_settings(
    http_request: Request,
    request: SetModelRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> ModelSettingsResponse:
    enforce_same_origin(http_request, settings)
    repo = AppSettingsRepository(db)
    try:
        model = repo.set_current_openai_model(request.model, allowed_models=settings.allowed_openai_models)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    AuthRepository(db).log_event(
        event_type="settings.model_changed",
        actor_user_id=current_user.user.id,
        target_type="app_setting",
        target_id="current_openai_model",
        email=current_user.user.primary_email,
        ip_address=get_request_ip(http_request),
        user_agent=get_request_user_agent(http_request),
        payload={"model": model},
    )
    return ModelSettingsResponse(
        current_model=model,
        allowed_models=settings.allowed_openai_models,
        has_api_key=bool(settings.openai_api_key),
    )
