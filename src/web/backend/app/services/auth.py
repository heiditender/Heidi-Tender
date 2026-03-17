from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from email.utils import parseaddr
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AuthProvider, User
from ..repositories.auth import AuthRepository, utc_now
from ..schemas import AuthProvidersResponse, AuthSessionResponse, AuthUserResponse
from ..auth.crypto import (
    build_expiring_signed_payload,
    generate_token,
    normalize_email,
    token_hash,
    verify_signed_payload,
)
from ..auth.oidc import OIDCError, build_authorize_url, exchange_code_for_tokens, fetch_userinfo, validate_id_token


MAGIC_LINK_REQUEST_EVENT = "auth.magic_link_requested"


@dataclass
class AuthenticatedIdentity:
    provider: AuthProvider
    provider_subject: str
    email: str
    email_verified: bool
    display_name: str | None
    avatar_url: str | None


def get_request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or None
    return request.client.host if request.client else None


def get_request_user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent", "").strip()
    return value or None


def is_safe_next_path(raw_path: str | None) -> str:
    if not raw_path:
        return "/console"
    text = raw_path.strip()
    if not text.startswith("/") or text.startswith("//"):
        return "/console"
    if text.startswith("/api/"):
        return "/console"
    if text.startswith("/login"):
        return "/console"
    return text


def append_query_param(path: str, key: str, value: str) -> str:
    parts = urlsplit(path)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[key] = value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def enforce_same_origin(request: Request, settings: Settings) -> None:
    origin = (request.headers.get("origin") or "").rstrip("/")
    referer = request.headers.get("referer") or ""
    if origin:
        if origin not in settings.trusted_web_origins:
            raise HTTPException(status_code=403, detail="cross-site request rejected")
        return
    if referer:
        parsed = urlsplit(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if referer_origin and referer_origin not in settings.trusted_web_origins:
            raise HTTPException(status_code=403, detail="cross-site request rejected")


def build_oauth_cookie(
    *,
    provider: str,
    state: str,
    nonce: str,
    code_verifier: str,
    next_path: str,
    settings: Settings,
) -> str:
    return build_expiring_signed_payload(
        {
            "provider": provider,
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "next_path": next_path,
        },
        settings.auth_session_secret,
        ttl_seconds=settings.auth_magic_link_ttl_seconds,
    )


def parse_oauth_cookie(raw_cookie: str | None, settings: Settings) -> dict[str, Any] | None:
    if not raw_cookie:
        return None
    return verify_signed_payload(raw_cookie, settings.auth_session_secret)


def provider_enabled(provider: str, settings: Settings) -> bool:
    if provider == "google":
        return bool(settings.auth_google_client_id and settings.auth_google_client_secret)
    if provider == "microsoft":
        return bool(settings.auth_microsoft_client_id and settings.auth_microsoft_client_secret)
    return False


def magic_link_enabled(settings: Settings) -> bool:
    return bool(settings.auth_resend_api_key and settings.auth_magic_link_sender_email)


def auth_provider_options(settings: Settings) -> AuthProvidersResponse:
    return AuthProvidersResponse(
        google=provider_enabled("google", settings),
        microsoft=provider_enabled("microsoft", settings),
        magic_link=magic_link_enabled(settings),
    )


def build_provider_login(
    *,
    provider: str,
    next_path: str,
    settings: Settings,
) -> tuple[str, str]:
    if not provider_enabled(provider, settings):
        raise HTTPException(status_code=503, detail=f"{provider} login is not configured")
    state = generate_token(24)
    nonce = generate_token(24)
    code_verifier = generate_token(32)
    try:
        redirect_url = build_authorize_url(
            provider=provider,
            settings=settings,
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
        )
    except OIDCError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    cookie_payload = build_oauth_cookie(
        provider=provider,
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        next_path=is_safe_next_path(next_path),
        settings=settings,
    )
    return redirect_url, cookie_payload


def _is_verified_email(provider: str, claims: dict[str, Any], userinfo: dict[str, Any]) -> bool:
    if provider == "google":
        return bool(claims.get("email_verified") or userinfo.get("email_verified"))
    if provider == "microsoft":
        return bool(userinfo.get("email") or claims.get("preferred_username") or claims.get("email"))
    return False


def authenticate_provider_callback(
    *,
    provider: str,
    code: str,
    state: str,
    raw_oauth_cookie: str | None,
    db: Session,
    settings: Settings,
) -> tuple[User, str, str]:
    payload = parse_oauth_cookie(raw_oauth_cookie, settings)
    if payload is None:
        raise HTTPException(status_code=400, detail="login state is missing or expired")
    if payload.get("provider") != provider or payload.get("state") != state:
        raise HTTPException(status_code=400, detail="login state mismatch")

    try:
        token_payload = exchange_code_for_tokens(
            provider=provider,
            settings=settings,
            code=code,
            code_verifier=str(payload["code_verifier"]),
        )
        id_token = str(token_payload.get("id_token") or "")
        access_token = str(token_payload.get("access_token") or "")
        if not id_token or not access_token:
            raise OIDCError(f"{provider} token response is missing id_token or access_token")
        claims = validate_id_token(
            provider=provider,
            settings=settings,
            id_token=id_token,
            nonce=str(payload["nonce"]),
        )
        userinfo = fetch_userinfo(provider=provider, settings=settings, access_token=access_token)
    except OIDCError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    provider_subject = str(userinfo.get("sub") or claims.get("sub") or "").strip()
    email = normalize_email(
        str(
            userinfo.get("email")
            or claims.get("email")
            or claims.get("preferred_username")
            or ""
        )
    )
    email_verified = _is_verified_email(provider, claims, userinfo)
    if not provider_subject or not email or not email_verified:
        raise HTTPException(status_code=403, detail="provider identity did not return a verified email")

    identity = AuthenticatedIdentity(
        provider=AuthProvider(provider),
        provider_subject=provider_subject,
        email=email,
        email_verified=email_verified,
        display_name=str(userinfo.get("name") or claims.get("name") or "").strip() or None,
        avatar_url=str(userinfo.get("picture") or claims.get("picture") or "").strip() or None,
    )
    repo = AuthRepository(db)
    user, _, _ = repo.create_or_link_identity(
        provider=identity.provider,
        provider_subject=identity.provider_subject,
        email=identity.email,
        email_verified=identity.email_verified,
        display_name=identity.display_name,
        avatar_url=identity.avatar_url,
    )
    repo.log_event(
        event_type="auth.login",
        actor_user_id=user.id,
        email=user.primary_email,
        payload={"provider": provider},
    )
    return user, identity.email, str(payload.get("next_path") or "/console")


def issue_session(
    *,
    db: Session,
    settings: Settings,
    user: User,
    request: Request,
) -> str:
    raw_token = generate_token(32)
    repo = AuthRepository(db)
    repo.create_session(
        user_id=user.id,
        token_hash_value=token_hash(raw_token, settings.auth_session_secret),
        idle_timeout_seconds=settings.auth_session_idle_timeout_seconds,
        absolute_timeout_seconds=settings.auth_session_absolute_timeout_seconds,
        created_ip=get_request_ip(request),
        user_agent=get_request_user_agent(request),
    )
    return raw_token


def revoke_session_token(*, db: Session, settings: Settings, raw_token: str | None) -> None:
    if not raw_token:
        return
    repo = AuthRepository(db)
    session = repo.get_session_by_token_hash(token_hash(raw_token, settings.auth_session_secret))
    if session is None:
        return
    repo.log_event(
        event_type="auth.logout",
        actor_user_id=session.user_id,
        email=session.user.primary_email if session.user else None,
    )
    repo.revoke_session(session)


def create_magic_link_request(
    *,
    db: Session,
    settings: Settings,
    email: str,
    next_path: str,
    request: Request,
) -> str:
    if not magic_link_enabled(settings):
        raise HTTPException(status_code=503, detail="magic link login is not configured")

    normalized_email = normalize_email(email)
    if not parseaddr(normalized_email)[1]:
        raise HTTPException(status_code=422, detail="invalid email address")

    repo = AuthRepository(db)
    now = utc_now()
    window_start = now - timedelta(seconds=settings.auth_rate_limit_window_seconds)
    request_ip = get_request_ip(request)

    recent_email_requests = repo.count_recent_events(
        event_type=MAGIC_LINK_REQUEST_EVENT,
        email=normalized_email,
        since=window_start,
    )
    if recent_email_requests >= settings.auth_magic_link_requests_per_email_window:
        raise HTTPException(status_code=429, detail="too many login link requests for this email")

    if request_ip:
        recent_ip_requests = repo.count_recent_events(
            event_type=MAGIC_LINK_REQUEST_EVENT,
            ip_address=request_ip,
            since=window_start,
        )
        if recent_ip_requests >= settings.auth_magic_link_requests_per_ip_window:
            raise HTTPException(status_code=429, detail="too many login link requests from this IP")

    raw_token = generate_token(32)
    repo.create_magic_link_token(
        email=normalized_email,
        token_hash_value=token_hash(raw_token, settings.auth_session_secret),
        next_path=is_safe_next_path(next_path),
        requested_ip=request_ip,
        ttl_seconds=settings.auth_magic_link_ttl_seconds,
    )
    repo.log_event(
        event_type=MAGIC_LINK_REQUEST_EVENT,
        email=normalized_email,
        ip_address=request_ip,
        user_agent=get_request_user_agent(request),
    )
    return raw_token


def consume_magic_link(
    *,
    db: Session,
    settings: Settings,
    raw_token: str,
) -> tuple[User, str]:
    repo = AuthRepository(db)
    token_row = repo.consume_magic_link(token_hash(raw_token, settings.auth_session_secret))
    if token_row is None:
        raise HTTPException(status_code=400, detail="login link is invalid or expired")

    user, _, _ = repo.create_or_link_identity(
        provider=AuthProvider.magic_link,
        provider_subject=token_row.email,
        email=token_row.email,
        email_verified=True,
        display_name=None,
        avatar_url=None,
    )
    repo.log_event(
        event_type="auth.login",
        actor_user_id=user.id,
        email=user.primary_email,
        payload={"provider": "magic_link"},
    )
    return user, is_safe_next_path(token_row.next_path)


def session_to_response(user: User) -> AuthSessionResponse:
    return AuthSessionResponse(
        user=AuthUserResponse(
            id=user.id,
            email=user.primary_email,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        )
    )
