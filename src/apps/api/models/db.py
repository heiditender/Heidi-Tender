from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from apps.api.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TenderNotice(Base):
    __tablename__ = "tender_notices"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_notice_source_source_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    buyer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    buyer_location: Mapped[str | None] = mapped_column(String(255))
    cpv_codes: Mapped[list[str] | None] = mapped_column(JSON)
    procedure_type: Mapped[str | None] = mapped_column(String(128))
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deadline_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    languages: Mapped[list[str] | None] = mapped_column(JSON)
    region: Mapped[str | None] = mapped_column(String(128), index=True)
    url: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list[dict] | None] = mapped_column(JSON)
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    document_refs: Mapped[list[DocumentRef]] = relationship(back_populates="notice", cascade="all, delete-orphan")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="notice", cascade="all, delete-orphan")
    versions: Mapped[list[NoticeVersion]] = relationship(back_populates="notice", cascade="all, delete-orphan")


class DocumentRef(Base):
    __tablename__ = "document_refs"

    doc_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    notice_id: Mapped[str] = mapped_column(String(36), ForeignKey("tender_notices.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text, index=True)
    filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    raw_bytes_path: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    notice: Mapped[TenderNotice] = relationship(back_populates="document_refs")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("notice_id", "doc_id", "chunk_index", name="uq_chunk_position"),)

    chunk_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("document_refs.doc_id", ondelete="CASCADE"), index=True)
    notice_id: Mapped[str] = mapped_column(String(36), ForeignKey("tender_notices.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    notice: Mapped[TenderNotice] = relationship(back_populates="chunks")


class NoticeVersion(Base):
    __tablename__ = "notice_versions"
    __table_args__ = (UniqueConstraint("notice_id", "content_hash", name="uq_notice_version_hash"),)

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    notice_id: Mapped[str] = mapped_column(String(36), ForeignKey("tender_notices.id", ondelete="CASCADE"), index=True)
    version_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_json_snapshot: Mapped[dict] = mapped_column(JSON)

    notice: Mapped[TenderNotice] = relationship(back_populates="versions")


settings = get_settings()
if settings.db_require_postgres and settings.app_env.lower() != "test":
    if not settings.db_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("PostgreSQL is required. Please set DB_URL to a postgres URL.")

engine = create_engine(settings.db_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    # Reserved for tests only; runtime schema management is handled by Alembic.
    if settings.app_env.lower() == "test":
        Base.metadata.create_all(bind=engine)


def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
