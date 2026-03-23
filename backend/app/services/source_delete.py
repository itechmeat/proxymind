from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, KnowledgeSnapshot, Source
from app.db.models.enums import SnapshotStatus, SourceStatus


class ChunkDeletionClient(Protocol):
    async def delete_chunks(self, chunk_ids: list[uuid.UUID]) -> None: ...


class SourceNotFoundError(RuntimeError):
    pass


@dataclass(slots=True)
class SourceDeleteResult:
    source: Source
    warnings: list[str]


class SourceDeleteService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        qdrant_service: ChunkDeletionClient | None,
    ) -> None:
        self._session = session
        self._qdrant_service = qdrant_service

    async def soft_delete(
        self,
        source_id: uuid.UUID,
        *,
        agent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
    ) -> SourceDeleteResult:
        source = await self._session.scalar(
            select(Source)
            .where(
                Source.id == source_id,
                Source.agent_id == agent_id,
                Source.knowledge_base_id == knowledge_base_id,
            )
            .with_for_update()
        )
        if source is None:
            raise SourceNotFoundError("Source not found")
        if source.status is SourceStatus.DELETED:
            return SourceDeleteResult(source=source, warnings=[])

        source.status = SourceStatus.DELETED
        source.deleted_at = datetime.now(UTC)

        chunk_rows = (
            await self._session.execute(
                select(Chunk.id, Chunk.snapshot_id, KnowledgeSnapshot.status)
                .join(KnowledgeSnapshot, KnowledgeSnapshot.id == Chunk.snapshot_id)
                .where(Chunk.source_id == source_id)
            )
        ).all()

        draft_chunk_ids: list[uuid.UUID] = []
        draft_counts: dict[uuid.UUID, int] = {}
        affected_live_snapshots: set[uuid.UUID] = set()
        for chunk_id, snapshot_id, snapshot_status in chunk_rows:
            if snapshot_status is SnapshotStatus.DRAFT:
                draft_chunk_ids.append(chunk_id)
                draft_counts[snapshot_id] = draft_counts.get(snapshot_id, 0) + 1
            elif snapshot_status in {SnapshotStatus.PUBLISHED, SnapshotStatus.ACTIVE}:
                affected_live_snapshots.add(snapshot_id)

        if draft_chunk_ids:
            if self._qdrant_service is None:
                raise RuntimeError("Qdrant service is required for draft chunk cleanup")
            # Prefer orphaned draft rows over searchable stale vectors if a later
            # PostgreSQL step fails after draft cleanup has already started.
            await self._qdrant_service.delete_chunks(draft_chunk_ids)
            await self._session.execute(delete(Chunk).where(Chunk.id.in_(draft_chunk_ids)))
            for snapshot_id, removed_count in draft_counts.items():
                await self._session.execute(
                    update(KnowledgeSnapshot)
                    .where(KnowledgeSnapshot.id == snapshot_id)
                    .values(chunk_count=KnowledgeSnapshot.chunk_count - removed_count)
                )

        warnings: list[str] = []
        if affected_live_snapshots:
            warnings.append(
                "Source is referenced in "
                f"{len(affected_live_snapshots)} published/active snapshot(s). "
                "Chunks will remain visible until a new snapshot replaces them."
            )

        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return SourceDeleteResult(source=source, warnings=warnings)
