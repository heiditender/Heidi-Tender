"""init schema for suisse bid match

Revision ID: 20260305_0001
Revises:
Create Date: 2026-03-05 10:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260305_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tender_notices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("buyer_name", sa.String(length=255), nullable=True),
        sa.Column("buyer_location", sa.String(length=255), nullable=True),
        sa.Column("cpv_codes", sa.JSON(), nullable=True),
        sa.Column("procedure_type", sa.String(length=128), nullable=True),
        sa.Column("publication_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("documents", sa.JSON(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "source_id", name="uq_notice_source_source_id"),
    )
    op.create_index("ix_tender_notices_source", "tender_notices", ["source"])
    op.create_index("ix_tender_notices_source_id", "tender_notices", ["source_id"])
    op.create_index("ix_tender_notices_buyer_name", "tender_notices", ["buyer_name"])
    op.create_index("ix_tender_notices_publication_date", "tender_notices", ["publication_date"])
    op.create_index("ix_tender_notices_deadline_date", "tender_notices", ["deadline_date"])
    op.create_index("ix_tender_notices_region", "tender_notices", ["region"])

    op.create_table(
        "document_refs",
        sa.Column("doc_id", sa.String(length=36), primary_key=True),
        sa.Column("notice_id", sa.String(length=36), sa.ForeignKey("tender_notices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("raw_bytes_path", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_refs_notice_id", "document_refs", ["notice_id"])
    op.create_index("ix_document_refs_url", "document_refs", ["url"])
    op.create_index("ix_document_refs_sha256", "document_refs", ["sha256"])

    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(length=36), primary_key=True),
        sa.Column("doc_id", sa.String(length=36), sa.ForeignKey("document_refs.doc_id", ondelete="CASCADE"), nullable=True),
        sa.Column("notice_id", sa.String(length=36), sa.ForeignKey("tender_notices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("notice_id", "doc_id", "chunk_index", name="uq_chunk_position"),
    )
    op.create_index("ix_chunks_doc_id", "chunks", ["doc_id"])
    op.create_index("ix_chunks_notice_id", "chunks", ["notice_id"])

    op.create_table(
        "notice_versions",
        sa.Column("version_id", sa.String(length=36), primary_key=True),
        sa.Column("notice_id", sa.String(length=36), sa.ForeignKey("tender_notices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_json_snapshot", sa.JSON(), nullable=False),
        sa.UniqueConstraint("notice_id", "content_hash", name="uq_notice_version_hash"),
    )
    op.create_index("ix_notice_versions_notice_id", "notice_versions", ["notice_id"])
    op.create_index("ix_notice_versions_version_ts", "notice_versions", ["version_ts"])
    op.create_index("ix_notice_versions_content_hash", "notice_versions", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_notice_versions_content_hash", table_name="notice_versions")
    op.drop_index("ix_notice_versions_version_ts", table_name="notice_versions")
    op.drop_index("ix_notice_versions_notice_id", table_name="notice_versions")
    op.drop_table("notice_versions")

    op.drop_index("ix_chunks_notice_id", table_name="chunks")
    op.drop_index("ix_chunks_doc_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_document_refs_sha256", table_name="document_refs")
    op.drop_index("ix_document_refs_url", table_name="document_refs")
    op.drop_index("ix_document_refs_notice_id", table_name="document_refs")
    op.drop_table("document_refs")

    op.drop_index("ix_tender_notices_region", table_name="tender_notices")
    op.drop_index("ix_tender_notices_deadline_date", table_name="tender_notices")
    op.drop_index("ix_tender_notices_publication_date", table_name="tender_notices")
    op.drop_index("ix_tender_notices_buyer_name", table_name="tender_notices")
    op.drop_index("ix_tender_notices_source_id", table_name="tender_notices")
    op.drop_index("ix_tender_notices_source", table_name="tender_notices")
    op.drop_table("tender_notices")
