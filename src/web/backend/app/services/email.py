from __future__ import annotations

import requests

from ..config import Settings


def send_magic_link_email(
    *,
    settings: Settings,
    to_email: str,
    raw_token: str,
) -> None:
    if not settings.auth_resend_api_key or not settings.auth_magic_link_sender_email:
        raise RuntimeError("Resend is not configured")

    verify_url = f"{settings.magic_link_base_url}{settings.api_prefix}/auth/magic-link/verify?token={raw_token}"
    payload = {
        "from": settings.auth_magic_link_sender_email,
        "to": [to_email],
        "subject": settings.auth_magic_link_subject,
        "html": (
            "<p>Use the secure link below to sign in to Heidi Tender.</p>"
            f"<p><a href=\"{verify_url}\">Sign in to Heidi Tender</a></p>"
            f"<p>This link expires in {settings.auth_magic_link_ttl_seconds // 60} minutes and can only be used once.</p>"
        ),
    }
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {settings.auth_resend_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.auth_http_timeout_seconds,
    )
    response.raise_for_status()
