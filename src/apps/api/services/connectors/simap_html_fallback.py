from __future__ import annotations


def not_enabled_message() -> dict:
    return {
        "enabled": False,
        "message": "SIMAP HTML fallback is intentionally disabled in this MVP. API connector is the supported path.",
    }
