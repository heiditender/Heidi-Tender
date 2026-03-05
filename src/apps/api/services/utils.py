from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            dt = date_parser.parse(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        chunks = [x.strip() for x in re.split(r"[,;|]", value) if x.strip()]
        return chunks if chunks else [value]
    return [value]


def canonical_json_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def safe_get(data: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        keys = path.split(".")
        curr: Any = data
        ok = True
        for key in keys:
            if isinstance(curr, dict) and key in curr:
                curr = curr[key]
            else:
                ok = False
                break
        if ok:
            return curr
    return None


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
