from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest

from app.auth.oidc import OIDCError, validate_id_token
from app.config import Settings


class _FakeJWKClient:
    def __init__(self, jwks_uri: str):
        self.jwks_uri = jwks_uri

    def get_signing_key_from_jwt(self, id_token: str) -> SimpleNamespace:
        return SimpleNamespace(key="public-key")


def _build_settings(tmp_path) -> Settings:
    return Settings(
        jobs_root=tmp_path / "jobs",
        auth_microsoft_client_id="microsoft-client-id",
        auth_microsoft_client_secret="microsoft-client-secret",
    )


def test_validate_id_token_accepts_microsoft_common_issuer_template(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)

    monkeypatch.setattr(
        "app.auth.oidc.get_provider_metadata",
        lambda *_: {
            "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
            "issuer": "https://login.microsoftonline.com/{tenantid}/v2.0",
        },
    )
    monkeypatch.setattr("app.auth.oidc.jwt.PyJWKClient", _FakeJWKClient)

    def _fake_decode(*args, **kwargs):
        assert kwargs["audience"] == "microsoft-client-id"
        assert kwargs["options"]["verify_iss"] is False
        return {
            "aud": "microsoft-client-id",
            "exp": 4_102_444_800,
            "iat": 1_700_000_000,
            "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
            "nonce": "nonce-value",
            "tid": "tenant-123",
        }

    monkeypatch.setattr("app.auth.oidc.jwt.decode", _fake_decode)

    claims = validate_id_token(
        provider="microsoft",
        settings=settings,
        id_token="header.payload.signature",
        nonce="nonce-value",
    )

    assert claims["iss"] == "https://login.microsoftonline.com/tenant-123/v2.0"


def test_validate_id_token_rejects_microsoft_tenant_mismatch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)

    monkeypatch.setattr(
        "app.auth.oidc.get_provider_metadata",
        lambda *_: {
            "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
            "issuer": "https://login.microsoftonline.com/{tenantid}/v2.0",
        },
    )
    monkeypatch.setattr("app.auth.oidc.jwt.PyJWKClient", _FakeJWKClient)
    monkeypatch.setattr(
        "app.auth.oidc.jwt.decode",
        lambda *args, **kwargs: {
            "aud": "microsoft-client-id",
            "exp": 4_102_444_800,
            "iat": 1_700_000_000,
            "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
            "nonce": "nonce-value",
            "tid": "tenant-456",
        },
    )

    with pytest.raises(OIDCError, match="microsoft id_token tenant mismatch"):
        validate_id_token(
            provider="microsoft",
            settings=settings,
            id_token="header.payload.signature",
            nonce="nonce-value",
        )


def test_validate_id_token_wraps_pyjwt_errors(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _build_settings(tmp_path)

    monkeypatch.setattr(
        "app.auth.oidc.get_provider_metadata",
        lambda *_: {
            "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
            "issuer": "https://login.microsoftonline.com/{tenantid}/v2.0",
        },
    )
    monkeypatch.setattr("app.auth.oidc.jwt.PyJWKClient", _FakeJWKClient)
    monkeypatch.setattr(
        "app.auth.oidc.jwt.decode",
        lambda *args, **kwargs: (_ for _ in ()).throw(jwt.InvalidIssuerError("Invalid issuer")),
    )

    with pytest.raises(OIDCError, match="microsoft id_token validation failed: Invalid issuer"):
        validate_id_token(
            provider="microsoft",
            settings=settings,
            id_token="header.payload.signature",
            nonce="nonce-value",
        )
