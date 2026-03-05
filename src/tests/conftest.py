import os
import tempfile

import pytest

# Keep tests lightweight with sqlite, while runtime stays postgres-only.
os.environ["APP_ENV"] = "test"
os.environ["DB_REQUIRE_POSTGRES"] = "false"
_fd, _path = tempfile.mkstemp(prefix="suisse_bid_match_test_", suffix=".db")
os.close(_fd)
os.environ["DB_URL"] = f"sqlite:///{_path}"
os.environ["QDRANT_URL"] = "http://localhost:6333"

from apps.api.models.db import SessionLocal, TenderNotice, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    init_db()


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture()
def sample_notice(db_session):
    notice = TenderNotice(source="simap", source_id="n1", title="Sample", description="desc")
    db_session.add(notice)
    db_session.commit()
    db_session.refresh(notice)
    return notice
