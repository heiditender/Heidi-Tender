from __future__ import annotations

from pathlib import Path
from typing import Generator

from fastapi import FastAPI
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import router as auth_router
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.models import AuthProvider, User, UserIdentity

pytest.importorskip("httpx")
from fastapi.testclient import TestClient


def _build_client(tmp_path: Path, *, per_email_limit: int = 5) -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    def _override_get_db() -> Generator[Session, None, None]:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    def _override_get_settings() -> Settings:
        return Settings(
            openai_api_key="test-key",
            jobs_root=tmp_path / "jobs",
            cors_allowed_origins="https://heiditender.ch",
            auth_session_secret="test-session-secret",
            auth_public_base_url="https://heiditender.ch",
            auth_frontend_base_url="https://heiditender.ch",
            auth_resend_api_key="re_test_key",
            auth_magic_link_sender_email="login@heiditender.ch",
            auth_magic_link_requests_per_email_window=per_email_limit,
            auth_magic_link_requests_per_ip_window=10,
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = _override_get_settings
    return TestClient(app, base_url="https://heiditender.ch"), testing_session


def test_magic_link_login_sets_session_and_returns_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, testing_session = _build_client(tmp_path)
    captured: dict[str, str] = {}

    def _fake_send_magic_link_email(*, settings: Settings, to_email: str, raw_token: str) -> None:
        captured["email"] = to_email
        captured["token"] = raw_token

    monkeypatch.setattr("app.services.email.send_magic_link_email", _fake_send_magic_link_email)

    response = client.post(
        "/api/v1/auth/magic-link/request",
        json={"email": "User@Example.com", "next_path": "/stats"},
        headers={"Origin": "https://heiditender.ch"},
    )

    assert response.status_code == 200
    assert captured["email"] == "User@Example.com"
    assert captured["token"]

    verify = client.get(
        "/api/v1/auth/magic-link/verify",
        params={"token": captured["token"]},
        follow_redirects=False,
    )

    assert verify.status_code == 302
    assert verify.headers["location"] == "https://heiditender.ch/stats"
    assert "__Host-heidi_session=" in verify.headers["set-cookie"]

    session_response = client.get("/api/v1/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["user"]["email"] == "user@example.com"

    with testing_session() as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].primary_email == "user@example.com"
        identities = db.scalars(select(UserIdentity)).all()
        assert len(identities) == 1
        assert identities[0].provider == AuthProvider.magic_link


def test_auth_options_reflect_disabled_magic_link(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)

    response = client.get("/api/v1/auth/options")

    assert response.status_code == 200
    assert response.json() == {
        "google": False,
        "microsoft": False,
        "magic_link": True,
    }


def test_magic_link_request_is_rate_limited_per_email(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, per_email_limit=1)
    monkeypatch.setattr("app.services.email.send_magic_link_email", lambda **_: None)

    first = client.post(
        "/api/v1/auth/magic-link/request",
        json={"email": "person@example.com"},
        headers={"Origin": "https://heiditender.ch"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/auth/magic-link/request",
        json={"email": "person@example.com"},
        headers={"Origin": "https://heiditender.ch"},
    )
    assert second.status_code == 429
    assert "too many login link requests" in second.text


def test_magic_link_request_rejects_when_unconfigured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path)
    monkeypatch.setattr("app.services.email.send_magic_link_email", lambda **_: None)

    def _override_get_settings() -> Settings:
        return Settings(
            openai_api_key="test-key",
            jobs_root=tmp_path / "jobs",
            cors_allowed_origins="https://heiditender.ch",
            auth_session_secret="test-session-secret",
            auth_public_base_url="https://heiditender.ch",
            auth_frontend_base_url="https://heiditender.ch",
        )

    client.app.dependency_overrides[get_settings] = _override_get_settings

    options = client.get("/api/v1/auth/options")
    assert options.status_code == 200
    assert options.json()["magic_link"] is False

    response = client.post(
        "/api/v1/auth/magic-link/request",
        json={"email": "person@example.com"},
        headers={"Origin": "https://heiditender.ch"},
    )
    assert response.status_code == 503
    assert "magic link login is not configured" in response.text


def test_logout_revokes_session_and_requires_same_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path)
    captured: dict[str, str] = {}

    def _fake_send_magic_link_email(*, settings: Settings, to_email: str, raw_token: str) -> None:
        captured["token"] = raw_token

    monkeypatch.setattr("app.services.email.send_magic_link_email", _fake_send_magic_link_email)

    request_response = client.post(
        "/api/v1/auth/magic-link/request",
        json={"email": "logout@example.com"},
        headers={"Origin": "https://heiditender.ch"},
    )
    assert request_response.status_code == 200

    verify = client.get(
        "/api/v1/auth/magic-link/verify",
        params={"token": captured["token"]},
        follow_redirects=False,
    )
    assert verify.status_code == 302

    forbidden = client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"})
    assert forbidden.status_code == 403

    logout = client.post("/api/v1/auth/logout", headers={"Origin": "https://heiditender.ch"})
    assert logout.status_code == 204

    session_response = client.get("/api/v1/auth/session")
    assert session_response.status_code == 401
