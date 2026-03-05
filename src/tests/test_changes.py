from datetime import datetime, timedelta, timezone

from apps.api.models.db import NoticeVersion
from apps.api.services.analysis.changes import calculate_changes


def test_changes_detects_deadline_change(db_session, sample_notice):
    v1 = NoticeVersion(
        notice_id=sample_notice.id,
        version_ts=datetime.now(timezone.utc) - timedelta(days=1),
        content_hash="h1",
        raw_json_snapshot={"deadline_date": "2026-04-01T00:00:00+00:00", "documents": ["a.pdf"], "description": "old"},
    )
    v2 = NoticeVersion(
        notice_id=sample_notice.id,
        version_ts=datetime.now(timezone.utc),
        content_hash="h2",
        raw_json_snapshot={"deadline_date": "2026-03-20T00:00:00+00:00", "documents": ["a.pdf", "b.pdf"], "description": "new"},
    )
    db_session.add_all([v1, v2])
    db_session.commit()

    out = calculate_changes(db_session, sample_notice.id)
    assert out.impact_label in {"med", "high"}
    assert any(d.field == "deadline_date" for d in out.diffs)
