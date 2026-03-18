from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    KnowledgeScopeMixin,
    PrimaryKeyMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
)
from app.db.models.enums import (
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SnapshotStatus,
    SourceStatus,
    SourceType,
    TaskType,
    pg_enum,
)

if TYPE_CHECKING:
    from app.db.models.core import CatalogItem


class Source(
    PrimaryKeyMixin,
    TenantMixin,
    KnowledgeScopeMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    __tablename__ = "sources"

    source_type: Mapped[SourceType] = mapped_column(
        pg_enum(SourceType, name="source_type_enum"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_items.id"),
        nullable=True,
    )
    status: Mapped[SourceStatus] = mapped_column(
        pg_enum(SourceStatus, name="source_status_enum"),
        nullable=False,
    )

    catalog_item: Mapped[CatalogItem | None] = relationship(back_populates="sources")
    documents: Mapped[list[Document]] = relationship(back_populates="source")


class Document(PrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        pg_enum(DocumentStatus, name="document_status_enum"),
        nullable=False,
    )

    source: Mapped[Source] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document")


class DocumentVersion(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_id_version_number",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    processing_path: Mapped[ProcessingPath | None] = mapped_column(
        pg_enum(ProcessingPath, name="processing_path_enum"),
        nullable=True,
    )
    status: Mapped[DocumentVersionStatus] = mapped_column(
        pg_enum(DocumentVersionStatus, name="document_version_status_enum"),
        nullable=False,
    )

    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document_version")


class Chunk(PrimaryKeyMixin, TenantMixin, KnowledgeScopeMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_chunks_document_version_id_chunk_index",
        ),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"),
        nullable=False,
    )
    # Both fields stay as plain UUIDs by design: snapshot_id avoids a circular FK path,
    # and source_id is denormalized for citation lookup speed.
    snapshot_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_chapter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anchor_section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anchor_timecode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ChunkStatus] = mapped_column(
        pg_enum(ChunkStatus, name="chunk_status_enum"),
        nullable=False,
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")


class KnowledgeSnapshot(PrimaryKeyMixin, TenantMixin, KnowledgeScopeMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_snapshots"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SnapshotStatus] = mapped_column(
        pg_enum(SnapshotStatus, name="snapshot_status_enum"),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True)
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )


class EmbeddingProfile(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "embedding_profiles"

    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[TaskType] = mapped_column(
        pg_enum(TaskType, name="task_type_enum"),
        nullable=False,
    )
    pipeline_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
