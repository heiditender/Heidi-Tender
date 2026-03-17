"""Auth, session, audit, and ownership bootstrap.

Revision ID: 20260317_0001
Revises:
Create Date: 2026-03-17 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260317_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _column_names(inspector, table_name: str) -> set[str]:
    if not _table_exists(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector, table_name: str) -> set[str]:
    if not _table_exists(inspector, table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_base_app_tables(inspector) -> None:
    if not _table_exists(inspector, "jobs"):
        op.create_table(
            "jobs",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("status", sa.Enum("created", "uploading", "ready", "running", "succeeded", "failed", name="jobstatus"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("runtime_dir", sa.Text(), nullable=True),
            sa.Column("final_output_path", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("rule_version_id", sa.String(length=36), nullable=True),
            sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        )
    if not _table_exists(inspector, "job_files"):
        op.create_table(
            "job_files",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("relative_path", sa.Text(), nullable=False),
            sa.Column("stored_path", sa.Text(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("extension", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.UniqueConstraint("job_id", "relative_path", name="uq_job_file_path"),
        )
    if not _table_exists(inspector, "job_steps"):
        op.create_table(
            "job_steps",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("step_name", sa.String(length=128), nullable=False),
            sa.Column("step_status", sa.String(length=32), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.UniqueConstraint("job_id", "step_name", name="uq_job_step_name"),
        )
    if not _table_exists(inspector, "job_events"):
        op.create_table(
            "job_events",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        )
    if not _table_exists(inspector, "rule_versions"):
        op.create_table(
            "rule_versions",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.Enum("draft", "published", "archived", name="rulestatus"), nullable=False),
            sa.Column("source", sa.Enum("manual", "llm", "seed", name="rulesource"), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("validation_report", sa.JSON(), nullable=False),
            sa.Column("copilot_log", sa.JSON(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
            sa.UniqueConstraint("version_number"),
        )
    if not _table_exists(inspector, "app_settings"):
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(length=128), primary_key=True, nullable=False),
            sa.Column("value", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name

    _create_base_app_tables(inspector)
    inspector = inspect(bind)

    if not _table_exists(inspector, "users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("primary_email", sa.String(length=320), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("avatar_url", sa.Text(), nullable=True),
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("primary_email", name="uq_users_primary_email"),
        )

    if not _table_exists(inspector, "user_identities"):
        op.create_table(
            "user_identities",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("provider_subject", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("avatar_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.UniqueConstraint("provider", "provider_subject", name="uq_user_identity_provider_subject"),
        )

    if not _table_exists(inspector, "user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        )

    if not _table_exists(inspector, "magic_link_tokens"):
        op.create_table(
            "magic_link_tokens",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("next_path", sa.Text(), nullable=True),
            sa.Column("requested_ip", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_magic_link_tokens_token_hash"),
        )

    if not _table_exists(inspector, "audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=True),
            sa.Column("target_id", sa.String(length=128), nullable=True),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        )

    inspector = inspect(bind)
    job_columns = _column_names(inspector, "jobs")
    if "owner_user_id" not in job_columns:
        with op.batch_alter_table("jobs") as batch_op:
            batch_op.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
    rule_columns = _column_names(inspector, "rule_versions")
    if "copilot_log" not in rule_columns:
        with op.batch_alter_table("rule_versions") as batch_op:
            batch_op.add_column(sa.Column("copilot_log", sa.JSON(), nullable=True))
    if "created_by_user_id" not in rule_columns:
        with op.batch_alter_table("rule_versions") as batch_op:
            batch_op.add_column(sa.Column("created_by_user_id", sa.String(length=36), nullable=True))

    inspector = inspect(bind)
    if "ix_jobs_owner_user_id" not in _index_names(inspector, "jobs"):
        op.create_index("ix_jobs_owner_user_id", "jobs", ["owner_user_id"], unique=False)
    if "ix_rule_versions_created_by_user_id" not in _index_names(inspector, "rule_versions"):
        op.create_index("ix_rule_versions_created_by_user_id", "rule_versions", ["created_by_user_id"], unique=False)
    if "ix_users_primary_email" not in _index_names(inspector, "users"):
        op.create_index("ix_users_primary_email", "users", ["primary_email"], unique=True)
    if "ix_user_identities_user_id" not in _index_names(inspector, "user_identities"):
        op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"], unique=False)
    if "ix_user_identities_email" not in _index_names(inspector, "user_identities"):
        op.create_index("ix_user_identities_email", "user_identities", ["email"], unique=False)
    if "ix_user_sessions_user_id" not in _index_names(inspector, "user_sessions"):
        op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)
    if "ix_user_sessions_token_hash" not in _index_names(inspector, "user_sessions"):
        op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    if "ix_magic_link_tokens_email" not in _index_names(inspector, "magic_link_tokens"):
        op.create_index("ix_magic_link_tokens_email", "magic_link_tokens", ["email"], unique=False)
    if "ix_magic_link_tokens_token_hash" not in _index_names(inspector, "magic_link_tokens"):
        op.create_index("ix_magic_link_tokens_token_hash", "magic_link_tokens", ["token_hash"], unique=True)
    if "ix_audit_logs_event_type" not in _index_names(inspector, "audit_logs"):
        op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"], unique=False)
    if "ix_audit_logs_actor_user_id" not in _index_names(inspector, "audit_logs"):
        op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"], unique=False)
    if "ix_audit_logs_email" not in _index_names(inspector, "audit_logs"):
        op.create_index("ix_audit_logs_email", "audit_logs", ["email"], unique=False)
    if "ix_audit_logs_ip_address" not in _index_names(inspector, "audit_logs"):
        op.create_index("ix_audit_logs_ip_address", "audit_logs", ["ip_address"], unique=False)

    if dialect == "postgresql":
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_rule_versions_single_published ON rule_versions (status) WHERE status = 'published'"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_status_updated_at_desc ON jobs (status, updated_at DESC)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_updated_at_desc ON jobs (updated_at DESC)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_rule_versions_status_version_number_desc ON rule_versions (status, version_number DESC)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_rule_versions_source_version_number_desc ON rule_versions (source, version_number DESC)"))
    else:
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_status_updated_at_desc ON jobs (status, updated_at)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_updated_at_desc ON jobs (updated_at)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_rule_versions_status_version_number_desc ON rule_versions (status, version_number)"))
        bind.execute(text("CREATE INDEX IF NOT EXISTS ix_rule_versions_source_version_number_desc ON rule_versions (source, version_number)"))


def downgrade() -> None:
    pass
