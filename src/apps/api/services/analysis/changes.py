from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.models.db import NoticeVersion
from apps.api.models.schemas import ChangeItem, ChangesResponse, NoticeVersionOut


WATCH_FIELDS = ["deadline_date", "documents", "description", "requirements_hints"]


def _extract_requirements_hints(snapshot: dict[str, Any]) -> list[str]:
    text = (snapshot.get("description") or "").lower()
    hints = []
    for kw in ["must", "required", "mandatory", "submit", "eligibility", "qualification"]:
        if kw in text:
            hints.append(kw)
    return sorted(set(hints))


def _snapshot_for_diff(snapshot: dict[str, Any]) -> dict[str, Any]:
    data = dict(snapshot)
    data["requirements_hints"] = _extract_requirements_hints(snapshot)
    return data


def _diff_values(old: Any, new: Any, field: str) -> ChangeItem | None:
    if old == new:
        return None
    if old is None and new is not None:
        t = "added"
    elif old is not None and new is None:
        t = "removed"
    else:
        t = "changed"
    return ChangeItem(field=field, old=old, new=new, type=t)


def _impact_label(diffs: list[ChangeItem]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    label = "low"

    for d in diffs:
        field = d.field
        if field == "deadline_date":
            label = "high"
            reasons.append("Deadline changed; may alter bid timeline.")
        elif field == "documents":
            label = "med" if label != "high" else label
            reasons.append("Document list changed; submission package may need updates.")
        elif field == "requirements_hints":
            label = "high" if d.type in ("added", "changed") else label
            reasons.append("Requirements terms changed; eligibility risk increased.")
        elif field == "description":
            label = "med" if label == "low" else label
            reasons.append("Description changed; review scope/wording updates.")

    if not reasons:
        reasons.append("No material changes detected.")

    return label, reasons


def calculate_changes(db: Session, notice_id: str) -> ChangesResponse:
    versions = list(
        db.scalars(
            select(NoticeVersion)
            .where(NoticeVersion.notice_id == notice_id)
            .order_by(NoticeVersion.version_ts.desc())
        ).all()
    )

    version_items = [
        NoticeVersionOut(version_id=v.version_id, version_ts=v.version_ts, content_hash=v.content_hash)
        for v in versions
    ]

    if len(versions) < 2:
        return ChangesResponse(
            notice_id=notice_id,
            versions=version_items,
            diffs=[],
            impact_label="low",
            impact_reasons=["Only one version available; no diff to compare."],
        )

    newest = _snapshot_for_diff(versions[0].raw_json_snapshot or {})
    previous = _snapshot_for_diff(versions[1].raw_json_snapshot or {})

    diffs: list[ChangeItem] = []
    for field in WATCH_FIELDS:
        item = _diff_values(previous.get(field), newest.get(field), field)
        if item:
            diffs.append(item)

    impact_label, reasons = _impact_label(diffs)

    return ChangesResponse(
        notice_id=notice_id,
        versions=version_items,
        diffs=diffs,
        impact_label=impact_label,
        impact_reasons=reasons,
    )
