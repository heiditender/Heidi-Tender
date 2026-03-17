from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import User, UserSession
from ..repositories.auth import AuthRepository
from .crypto import token_hash


@dataclass
class SessionUser:
    user: User
    session: UserSession


def _resolve_session_user(
    request: Request,
    db: Session,
    settings: Settings,
) -> SessionUser | None:
    cached = getattr(request.state, "session_user", None)
    if cached is not None:
        return cached

    raw_token = request.cookies.get(settings.auth_session_cookie_name)
    if not raw_token:
        request.state.session_user = None
        return None

    repo = AuthRepository(db)
    session = repo.get_session_by_token_hash(token_hash(raw_token, settings.auth_session_secret))
    if session is None:
        request.state.session_user = None
        return None
    if repo.is_session_expired(session):
        repo.revoke_session(session)
        request.state.session_user = None
        return None

    session = repo.touch_session(
        session,
        idle_timeout_seconds=settings.auth_session_idle_timeout_seconds,
    )
    resolved = SessionUser(user=session.user, session=session)
    request.state.session_user = resolved
    return resolved


def get_optional_session_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionUser | None:
    return _resolve_session_user(request, db, settings)


def get_current_user(session_user: SessionUser | None = Depends(get_optional_session_user)) -> SessionUser:
    if session_user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return session_user
