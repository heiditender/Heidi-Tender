from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import jwt
import requests

from ..config import Settings
from .crypto import build_pkce_challenge


GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
MICROSOFT_DISCOVERY_URL = "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"


class OIDCError(RuntimeError):
    pass


def _fetch_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise OIDCError(f"invalid JSON payload from {url}")
    return payload


@lru_cache(maxsize=8)
def get_provider_metadata(discovery_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _fetch_json(discovery_url, timeout_seconds)


def _provider_settings(provider: str, settings: Settings) -> tuple[str, str, str]:
    if provider == "google":
        if not settings.auth_google_client_id or not settings.auth_google_client_secret:
            raise OIDCError("Google login is not configured")
        return GOOGLE_DISCOVERY_URL, settings.auth_google_client_id, settings.auth_google_client_secret
    if provider == "microsoft":
        if not settings.auth_microsoft_client_id or not settings.auth_microsoft_client_secret:
            raise OIDCError("Microsoft login is not configured")
        return MICROSOFT_DISCOVERY_URL, settings.auth_microsoft_client_id, settings.auth_microsoft_client_secret
    raise OIDCError(f"unsupported provider: {provider}")


def get_redirect_uri(provider: str, settings: Settings) -> str:
    if provider == "google":
        return settings.google_redirect_uri
    if provider == "microsoft":
        return settings.microsoft_redirect_uri
    raise OIDCError(f"unsupported provider: {provider}")


def build_authorize_url(
    *,
    provider: str,
    settings: Settings,
    state: str,
    nonce: str,
    code_verifier: str,
) -> str:
    discovery_url, client_id, _ = _provider_settings(provider, settings)
    metadata = get_provider_metadata(discovery_url, settings.auth_http_timeout_seconds)
    params = {
        "client_id": client_id,
        "redirect_uri": get_redirect_uri(provider, settings),
        "response_type": "code",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": build_pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{metadata['authorization_endpoint']}?{urlencode(params)}"


def exchange_code_for_tokens(
    *,
    provider: str,
    settings: Settings,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    discovery_url, client_id, client_secret = _provider_settings(provider, settings)
    metadata = get_provider_metadata(discovery_url, settings.auth_http_timeout_seconds)
    response = requests.post(
        metadata["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": get_redirect_uri(provider, settings),
            "code_verifier": code_verifier,
        },
        timeout=settings.auth_http_timeout_seconds,
    )
    if response.status_code >= 400:
        raise OIDCError(f"{provider} token exchange failed: {response.text[:300]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise OIDCError(f"{provider} token exchange returned invalid JSON")
    return payload


def validate_id_token(
    *,
    provider: str,
    settings: Settings,
    id_token: str,
    nonce: str,
) -> dict[str, Any]:
    discovery_url, client_id, _ = _provider_settings(provider, settings)
    metadata = get_provider_metadata(discovery_url, settings.auth_http_timeout_seconds)
    jwk_client = jwt.PyJWKClient(metadata["jwks_uri"])
    signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    payload = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=client_id,
        issuer=metadata["issuer"],
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    if payload.get("nonce") != nonce:
        raise OIDCError(f"{provider} id_token nonce mismatch")
    if not isinstance(payload, dict):
        raise OIDCError(f"{provider} id_token claims are invalid")
    return payload


def fetch_userinfo(*, provider: str, settings: Settings, access_token: str) -> dict[str, Any]:
    discovery_url, _, _ = _provider_settings(provider, settings)
    metadata = get_provider_metadata(discovery_url, settings.auth_http_timeout_seconds)
    endpoint = metadata.get("userinfo_endpoint")
    if not endpoint:
        raise OIDCError(f"{provider} userinfo endpoint is missing")
    response = requests.get(
        endpoint,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=settings.auth_http_timeout_seconds,
    )
    if response.status_code >= 400:
        raise OIDCError(f"{provider} userinfo lookup failed: {response.text[:300]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise OIDCError(f"{provider} userinfo returned invalid JSON")
    return payload
