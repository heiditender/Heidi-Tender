from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

from fastapi import FastAPI
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import SessionUser, get_current_user
from app.api.jobs import router as jobs_router
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.models import JobStatus, User, UserSession

pytest.importorskip("httpx")
from fastapi.testclient import TestClient


def _build_session_user(user_id: str, email: str) -> SessionUser:
    now = datetime.now(timezone.utc)
    user = User(id=user_id, primary_email=email, email_verified=True)
    session = UserSession(
        id=f"sess-{user_id}",
        user_id=user_id,
        token_hash="hash",
        created_at=now,
        last_used_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(days=7),
    )
    return SessionUser(user=user, session=session)


def _build_client(tmp_path: Path) -> tuple[TestClient, dict[str, SessionUser], sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    app = FastAPI()
    app.include_router(jobs_router, prefix="/api/v1")
    current_actor = {"value": _build_session_user("user-a", "a@example.com")}

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
            cors_allowed_origins="http://localhost:3000",
            auth_public_base_url="http://localhost:8000",
            auth_frontend_base_url="http://localhost:3000",
            auth_session_secret="test-secret",
        )

    def _override_current_user() -> SessionUser:
        return current_actor["value"]

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = _override_get_settings
    app.dependency_overrides[get_current_user] = _override_current_user
    return TestClient(app), current_actor, testing_session


def test_jobs_are_isolated_per_user(tmp_path: Path) -> None:
    client, current_actor, _ = _build_client(tmp_path)

    create_response = client.post("/api/v1/jobs", headers={"Origin": "http://localhost:3000"})
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]

    list_response = client.get("/api/v1/jobs")
    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [job_id]

    current_actor["value"] = _build_session_user("user-b", "b@example.com")
    list_response_other = client.get("/api/v1/jobs")
    assert list_response_other.status_code == 200
    assert list_response_other.json() == []

    detail_response_other = client.get(f"/api/v1/jobs/{job_id}")
    assert detail_response_other.status_code == 404


def test_job_creation_rejects_cross_site_origin(tmp_path: Path) -> None:
    client, _, _ = _build_client(tmp_path)

    response = client.post("/api/v1/jobs", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert "cross-site request rejected" in response.text
