from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..config import Settings, get_settings
from ..db import get_db
from ..schemas import AuthProvidersResponse, AuthSessionResponse, MagicLinkRequest, MagicLinkRequestResponse
from ..services.auth import (
    auth_provider_options,
    append_query_param,
    authenticate_provider_callback,
    build_provider_login,
    create_magic_link_request,
    consume_magic_link,
    enforce_same_origin,
    issue_session,
    is_safe_next_path,
    revoke_session_token,
    session_to_response,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _frontend_redirect(settings: Settings, path: str) -> str:
    base = settings.auth_frontend_base_url.rstrip("/")
    return f"{base}{path}"


def _set_session_cookie(response: Response, settings: Settings, raw_token: str) -> None:
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=settings.auth_session_absolute_timeout_seconds,
    )


def _clear_cookie(response: Response, settings: Settings, cookie_name: str) -> None:
    response.delete_cookie(
        key=cookie_name,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


@router.get("/options", response_model=AuthProvidersResponse)
def get_auth_options(settings: Settings = Depends(get_settings)) -> AuthProvidersResponse:
    return auth_provider_options(settings)


@router.get("/login/google")
def login_google(
    settings: Settings = Depends(get_settings),
    next_path: str | None = Query(default=None),
):
    redirect_url, cookie_payload = build_provider_login(
        provider="google",
        next_path=is_safe_next_path(next_path),
        settings=settings,
    )
    response = RedirectResponse(redirect_url, status_code=302)
    response.set_cookie(
        key=settings.auth_oauth_cookie_name,
        value=cookie_payload,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=settings.auth_magic_link_ttl_seconds,
    )
    return response


@router.get("/login/microsoft")
def login_microsoft(
    settings: Settings = Depends(get_settings),
    next_path: str | None = Query(default=None),
):
    redirect_url, cookie_payload = build_provider_login(
        provider="microsoft",
        next_path=is_safe_next_path(next_path),
        settings=settings,
    )
    response = RedirectResponse(redirect_url, status_code=302)
    response.set_cookie(
        key=settings.auth_oauth_cookie_name,
        value=cookie_payload,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=settings.auth_magic_link_ttl_seconds,
    )
    return response


@router.get("/callback/google")
def callback_google(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        user, _, next_path = authenticate_provider_callback(
            provider="google",
            code=code,
            state=state,
            raw_oauth_cookie=request.cookies.get(settings.auth_oauth_cookie_name),
            db=db,
            settings=settings,
        )
    except HTTPException as exc:
        target = append_query_param("/login", "error", str(exc.detail))
        return RedirectResponse(_frontend_redirect(settings, target), status_code=302)

    session_token = issue_session(db=db, settings=settings, user=user, request=request)
    response = RedirectResponse(_frontend_redirect(settings, next_path), status_code=302)
    _set_session_cookie(response, settings, session_token)
    _clear_cookie(response, settings, settings.auth_oauth_cookie_name)
    return response


@router.get("/callback/microsoft")
def callback_microsoft(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        user, _, next_path = authenticate_provider_callback(
            provider="microsoft",
            code=code,
            state=state,
            raw_oauth_cookie=request.cookies.get(settings.auth_oauth_cookie_name),
            db=db,
            settings=settings,
        )
    except HTTPException as exc:
        target = append_query_param("/login", "error", str(exc.detail))
        return RedirectResponse(_frontend_redirect(settings, target), status_code=302)

    session_token = issue_session(db=db, settings=settings, user=user, request=request)
    response = RedirectResponse(_frontend_redirect(settings, next_path), status_code=302)
    _set_session_cookie(response, settings, session_token)
    _clear_cookie(response, settings, settings.auth_oauth_cookie_name)
    return response


@router.post("/magic-link/request", response_model=MagicLinkRequestResponse)
def request_magic_link(
    payload: MagicLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MagicLinkRequestResponse:
    enforce_same_origin(request, settings)
    raw_token = create_magic_link_request(
        db=db,
        settings=settings,
        email=payload.email,
        next_path=is_safe_next_path(payload.next_path),
        request=request,
    )

    from ..services.email import send_magic_link_email

    send_magic_link_email(
        settings=settings,
        to_email=payload.email,
        raw_token=raw_token,
    )
    return MagicLinkRequestResponse(detail="If the email is valid, a sign-in link has been sent.")


@router.get("/magic-link/verify")
def verify_magic_link(
    request: Request,
    token: str = Query(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        user, next_path = consume_magic_link(
            db=db,
            settings=settings,
            raw_token=token,
        )
    except HTTPException as exc:
        target = append_query_param("/login", "error", str(exc.detail))
        return RedirectResponse(_frontend_redirect(settings, target), status_code=302)

    session_token = issue_session(db=db, settings=settings, user=user, request=request) if request else ""
    response = RedirectResponse(_frontend_redirect(settings, next_path), status_code=302)
    if session_token:
        _set_session_cookie(response, settings, session_token)
    return response


@router.get("/session", response_model=AuthSessionResponse)
def get_auth_session(current_user = Depends(get_current_user)) -> AuthSessionResponse:
    return session_to_response(current_user.user)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    enforce_same_origin(request, settings)
    revoke_session_token(
        db=db,
        settings=settings,
        raw_token=request.cookies.get(settings.auth_session_cookie_name),
    )
    response = Response(status_code=204)
    _clear_cookie(response, settings, settings.auth_session_cookie_name)
    _clear_cookie(response, settings, settings.auth_oauth_cookie_name)
    return response
