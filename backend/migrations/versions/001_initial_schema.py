"""initial_schema

Revision ID: 001
Revises:
Create Date: 2026-03-18 11:08:16.253163

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

catalog_item_type_enum = postgresql.ENUM(
    "book",
    "course",
    "event",
    "merch",
    "other",
    name="catalog_item_type_enum",
    create_type=False,
)
batch_operation_type_enum = postgresql.ENUM(
    "embedding",
    "text_extraction",
    "reindex",
    "eval",
    name="batch_operation_type_enum",
    create_type=False,
)
batch_status_enum = postgresql.ENUM(
    "pending",
    "processing",
    "complete",
    "failed",
    "cancelled",
    name="batch_status_enum",
    create_type=False,
)
task_type_enum = postgresql.ENUM(
    "retrieval",
    "query",
    name="task_type_enum",
    create_type=False,
)
snapshot_status_enum = postgresql.ENUM(
    "draft",
    "published",
    "active",
    "archived",
    name="snapshot_status_enum",
    create_type=False,
)
session_status_enum = postgresql.ENUM(
    "active",
    "closed",
    name="session_status_enum",
    create_type=False,
)
session_channel_enum = postgresql.ENUM(
    "web",
    "api",
    "telegram",
    "facebook",
    "vk",
    "instagram",
    "tiktok",
    name="session_channel_enum",
    create_type=False,
)
message_role_enum = postgresql.ENUM(
    "user",
    "assistant",
    name="message_role_enum",
    create_type=False,
)
message_status_enum = postgresql.ENUM(
    "received",
    "streaming",
    "complete",
    "partial",
    "failed",
    name="message_status_enum",
    create_type=False,
)
source_type_enum = postgresql.ENUM(
    "markdown",
    "txt",
    "pdf",
    "docx",
    "html",
    "image",
    "audio",
    "video",
    name="source_type_enum",
    create_type=False,
)
source_status_enum = postgresql.ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    "deleted",
    name="source_status_enum",
    create_type=False,
)
document_status_enum = postgresql.ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    name="document_status_enum",
    create_type=False,
)
document_version_status_enum = postgresql.ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    name="document_version_status_enum",
    create_type=False,
)
processing_path_enum = postgresql.ENUM(
    "path_a",
    "path_b",
    name="processing_path_enum",
    create_type=False,
)
chunk_status_enum = postgresql.ENUM(
    "pending",
    "indexed",
    "failed",
    name="chunk_status_enum",
    create_type=False,
)
ENUM_TYPES = (
    batch_operation_type_enum,
    batch_status_enum,
    catalog_item_type_enum,
    chunk_status_enum,
    document_status_enum,
    document_version_status_enum,
    message_role_enum,
    message_status_enum,
    processing_path_enum,
    session_channel_enum,
    session_status_enum,
    snapshot_status_enum,
    source_status_enum,
    source_type_enum,
    task_type_enum,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "agents",
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.Column("active_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("default_knowledge_base_id", sa.UUID(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "batch_jobs",
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("batch_operation_name", sa.String(length=255), nullable=True),
        sa.Column("operation_type", batch_operation_type_enum, nullable=False),
        sa.Column("status", batch_status_enum, nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("processed_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batch_jobs_agent_id"), "batch_jobs", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_batch_jobs_knowledge_base_id"), "batch_jobs", ["knowledge_base_id"], unique=False
    )
    op.create_table(
        "catalog_items",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("item_type", catalog_item_type_enum, nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_catalog_items_agent_id"), "catalog_items", ["agent_id"], unique=False)
    op.create_index(op.f("ix_catalog_items_owner_id"), "catalog_items", ["owner_id"], unique=False)
    op.create_table(
        "embedding_profiles",
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("task_type", task_type_enum, nullable=False),
        sa.Column("pipeline_version", sa.String(length=255), nullable=True),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=True),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_embedding_profiles_knowledge_base_id"),
        "embedding_profiles",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_snapshots",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", snapshot_status_enum, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_snapshots_agent_id"), "knowledge_snapshots", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("ix_knowledge_snapshots_knowledge_base_id"),
        "knowledge_snapshots",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_snapshots_owner_id"), "knowledge_snapshots", ["owner_id"], unique=False
    )
    op.create_table(
        "sessions",
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("status", session_status_enum, nullable=False),
        sa.Column("message_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("channel", session_channel_enum, server_default=sa.text("'web'"), nullable=False),
        sa.Column("channel_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("visitor_id", sa.UUID(), nullable=True),
        sa.Column("external_user_id", sa.String(length=255), nullable=True),
        sa.Column("channel_connector", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_agent_id"), "sessions", ["agent_id"], unique=False)
    op.create_index(op.f("ix_sessions_owner_id"), "sessions", ["owner_id"], unique=False)
    op.create_table(
        "messages",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("role", message_role_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", message_status_enum, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("source_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_type_spans", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("token_count_prompt", sa.Integer(), nullable=True),
        sa.Column("token_count_completion", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("config_commit_hash", sa.String(length=255), nullable=True),
        sa.Column("config_content_hash", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_session_id",
        "messages",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "uq_messages_idempotency_key_not_null",
        "messages",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "sources",
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("public_url", sa.String(length=2048), nullable=True),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("catalog_item_id", sa.UUID(), nullable=True),
        sa.Column("status", source_status_enum, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sources_agent_id"), "sources", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_sources_knowledge_base_id"), "sources", ["knowledge_base_id"], unique=False
    )
    op.create_index(op.f("ix_sources_owner_id"), "sources", ["owner_id"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("source_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("config_commit_hash", sa.String(length=255), nullable=True),
        sa.Column("config_content_hash", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("token_count_prompt", sa.Integer(), nullable=True),
        sa.Column("token_count_completion", sa.Integer(), nullable=True),
        sa.Column("retrieval_chunks_count", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_agent_id"), "audit_logs", ["agent_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("status", document_status_enum, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_agent_id"), "documents", ["agent_id"], unique=False)
    op.create_index(op.f("ix_documents_owner_id"), "documents", ["owner_id"], unique=False)
    op.create_table(
        "document_versions",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("processing_path", processing_path_enum, nullable=True),
        sa.Column("status", document_version_status_enum, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chunks",
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("anchor_page", sa.Integer(), nullable=True),
        sa.Column("anchor_chapter", sa.String(length=255), nullable=True),
        sa.Column("anchor_section", sa.String(length=255), nullable=True),
        sa.Column("anchor_timecode", sa.String(length=64), nullable=True),
        sa.Column("status", chunk_status_enum, nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chunks_agent_id"), "chunks", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_chunks_knowledge_base_id"), "chunks", ["knowledge_base_id"], unique=False
    )
    op.create_index(op.f("ix_chunks_owner_id"), "chunks", ["owner_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_chunks_owner_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_knowledge_base_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_agent_id"), table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_index(op.f("ix_documents_owner_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_agent_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_audit_logs_agent_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_sources_owner_id"), table_name="sources")
    op.drop_index(op.f("ix_sources_knowledge_base_id"), table_name="sources")
    op.drop_index(op.f("ix_sources_agent_id"), table_name="sources")
    op.drop_table("sources")
    op.drop_index(
        "uq_messages_idempotency_key_not_null",
        table_name="messages",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_sessions_owner_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_agent_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_knowledge_snapshots_owner_id"), table_name="knowledge_snapshots")
    op.drop_index(
        op.f("ix_knowledge_snapshots_knowledge_base_id"), table_name="knowledge_snapshots"
    )
    op.drop_index(op.f("ix_knowledge_snapshots_agent_id"), table_name="knowledge_snapshots")
    op.drop_table("knowledge_snapshots")
    op.drop_index(op.f("ix_embedding_profiles_knowledge_base_id"), table_name="embedding_profiles")
    op.drop_table("embedding_profiles")
    op.drop_index(op.f("ix_catalog_items_owner_id"), table_name="catalog_items")
    op.drop_index(op.f("ix_catalog_items_agent_id"), table_name="catalog_items")
    op.drop_table("catalog_items")
    op.drop_index(op.f("ix_batch_jobs_knowledge_base_id"), table_name="batch_jobs")
    op.drop_index(op.f("ix_batch_jobs_agent_id"), table_name="batch_jobs")
    op.drop_table("batch_jobs")
    op.drop_table("agents")
    bind = op.get_bind()
    for enum_type in reversed(ENUM_TYPES):
        enum_type.drop(bind, checkfirst=True)
