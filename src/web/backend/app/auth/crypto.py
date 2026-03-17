from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def generate_token(num_bytes: int = 32) -> str:
    return secrets.token_urlsafe(num_bytes)


def token_hash(token: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def base64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = base64url_encode(serialized)
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{base64url_encode(signature)}"


def verify_signed_payload(token: str, secret: str) -> dict[str, Any] | None:
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    actual = base64url_decode(signature)
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        payload = json.loads(base64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    expires_at = payload.get("exp")
    if expires_at is not None:
        try:
            exp_dt = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
        except Exception:
            return None
        if exp_dt <= utc_now():
            return None
    return payload


def build_expiring_signed_payload(payload: dict[str, Any], secret: str, ttl_seconds: int) -> str:
    data = dict(payload)
    data["exp"] = (utc_now() + timedelta(seconds=max(ttl_seconds, 1))).timestamp()
    return sign_payload(data, secret)


def build_pkce_verifier() -> str:
    return base64url_encode(secrets.token_bytes(32))


def build_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64url_encode(digest)
