from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, Chunk, KnowledgeSnapshot
from app.db.models.enums import ChunkStatus, SnapshotStatus


class SnapshotNotFoundError(RuntimeError):
    pass


class SnapshotConflictError(RuntimeError):
    pass


class SnapshotValidationError(RuntimeError):
    pass


class SnapshotService:
    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session

    def _resolve_session(self, session: AsyncSession | None) -> AsyncSession:
        resolved_session = session or self._session
        if resolved_session is None:
            raise RuntimeError("SnapshotService requires an active database session")
        return resolved_session

    async def list_snapshots(
        self,
        *,
        agent_id: uuid.UUID | None = None,
        knowledge_base_id: uuid.UUID | None = None,
        statuses: Sequence[SnapshotStatus] | None = None,
        include_archived: bool = False,
        session: AsyncSession | None = None,
    ) -> list[KnowledgeSnapshot]:
        db_session = self._resolve_session(session)
        statement = select(KnowledgeSnapshot).order_by(KnowledgeSnapshot.created_at.desc())

        if agent_id is not None:
            statement = statement.where(KnowledgeSnapshot.agent_id == agent_id)
        if knowledge_base_id is not None:
            statement = statement.where(KnowledgeSnapshot.knowledge_base_id == knowledge_base_id)

        if statuses:
            statement = statement.where(KnowledgeSnapshot.status.in_(list(statuses)))
        elif not include_archived:
            statement = statement.where(KnowledgeSnapshot.status != SnapshotStatus.ARCHIVED)

        return list((await db_session.scalars(statement)).all())

    async def get_snapshot(
        self,
        snapshot_id: uuid.UUID,
        *,
        agent_id: uuid.UUID | None = None,
        knowledge_base_id: uuid.UUID | None = None,
        session: AsyncSession | None = None,
    ) -> KnowledgeSnapshot | None:
        db_session = self._resolve_session(session)
        conditions = [KnowledgeSnapshot.id == snapshot_id]
        if agent_id is not None:
            conditions.append(KnowledgeSnapshot.agent_id == agent_id)
        if knowledge_base_id is not None:
            conditions.append(KnowledgeSnapshot.knowledge_base_id == knowledge_base_id)

        return await db_session.scalar(select(KnowledgeSnapshot).where(*conditions))

    async def get_active_snapshot(
        self,
        *,
        agent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
        session: AsyncSession | None = None,
    ) -> KnowledgeSnapshot | None:
        db_session = self._resolve_session(session)
        return await db_session.scalar(
            select(KnowledgeSnapshot).where(
                KnowledgeSnapshot.agent_id == agent_id,
                KnowledgeSnapshot.knowledge_base_id == knowledge_base_id,
                KnowledgeSnapshot.status == SnapshotStatus.ACTIVE,
            )
        )

    async def get_or_create_draft(
        self,
        session: AsyncSession | None = None,
        *,
        agent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
    ) -> KnowledgeSnapshot:
        db_session = self._resolve_session(session)
        statement = (
            insert(KnowledgeSnapshot)
            .values(
                id=uuid.uuid7(),
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                name="Auto draft",
                description="Automatically created draft snapshot for ingestion.",
                status=SnapshotStatus.DRAFT,
            )
            .on_conflict_do_nothing(
                index_elements=["agent_id", "knowledge_base_id"],
                index_where=KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
            )
        )
        await db_session.execute(statement)

        snapshot = await db_session.scalar(
            select(KnowledgeSnapshot).where(
                KnowledgeSnapshot.agent_id == agent_id,
                KnowledgeSnapshot.knowledge_base_id == knowledge_base_id,
                KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
            )
        )
        if snapshot is None:
            raise RuntimeError("Failed to create or load draft knowledge snapshot")
        return snapshot

    async def ensure_draft_or_rebind(
        self,
        session: AsyncSession | None = None,
        *,
        snapshot_id: uuid.UUID,
        agent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
    ) -> KnowledgeSnapshot:
        db_session = self._resolve_session(session)
        snapshot = await self._get_snapshot_for_update(
            db_session,
            snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
        if snapshot is None:
            raise RuntimeError("Knowledge snapshot not found during draft lock acquisition")
        if snapshot.status is SnapshotStatus.DRAFT:
            return snapshot

        rebound_snapshot = await self.get_or_create_draft(
            db_session,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
        locked_rebound_snapshot = await self._get_snapshot_for_update(
            db_session,
            rebound_snapshot.id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
        if locked_rebound_snapshot is None:
            raise RuntimeError("Failed to lock rebound draft knowledge snapshot")
        if locked_rebound_snapshot.status is not SnapshotStatus.DRAFT:
            raise RuntimeError("Rebound knowledge snapshot is no longer a draft")
        return locked_rebound_snapshot

    async def publish(
        self,
        snapshot_id: uuid.UUID,
        *,
        activate: bool = False,
        agent_id: uuid.UUID | None = None,
        knowledge_base_id: uuid.UUID | None = None,
        session: AsyncSession | None = None,
    ) -> KnowledgeSnapshot:
        db_session = self._resolve_session(session)
        snapshot = await self._get_snapshot_for_update(
            db_session,
            snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
        if snapshot is None:
            raise SnapshotNotFoundError("Snapshot not found")
        if snapshot.status is not SnapshotStatus.DRAFT:
            raise SnapshotConflictError(
                f"Cannot publish: snapshot status is '{snapshot.status.value}', expected 'draft'"
            )

        indexed_chunk_count = await self._count_chunks(
            db_session,
            snapshot_id=snapshot.id,
            status=ChunkStatus.INDEXED,
        )
        if indexed_chunk_count == 0:
            raise SnapshotValidationError("Cannot publish: snapshot has no indexed chunks")

        failed_chunk_count = await self._count_chunks(
            db_session,
            snapshot_id=snapshot.id,
            status=ChunkStatus.FAILED,
        )
        if failed_chunk_count > 0:
            raise SnapshotValidationError(
                f"Cannot publish: {failed_chunk_count} chunks failed indexing"
            )

        pending_chunk_count = await self._count_chunks(
            db_session,
            snapshot_id=snapshot.id,
            status=ChunkStatus.PENDING,
        )
        if pending_chunk_count > 0:
            raise SnapshotValidationError(
                f"Cannot publish: {pending_chunk_count} chunks are still processing"
            )

        snapshot.status = SnapshotStatus.PUBLISHED
        snapshot.published_at = datetime.now(UTC)

        if activate:
            await self._do_activate(db_session, snapshot)

        return await self._commit_snapshot_change(
            db_session,
            snapshot,
            concurrent_detail="Cannot activate: concurrent active snapshot conflict detected",
        )

    async def activate(
        self,
        snapshot_id: uuid.UUID,
        *,
        agent_id: uuid.UUID | None = None,
        knowledge_base_id: uuid.UUID | None = None,
        session: AsyncSession | None = None,
    ) -> KnowledgeSnapshot:
        db_session = self._resolve_session(session)
        snapshot = await self._get_snapshot_for_update(
            db_session,
            snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
        if snapshot is None:
            raise SnapshotNotFoundError("Snapshot not found")
        if snapshot.status is not SnapshotStatus.PUBLISHED:
            raise SnapshotConflictError(self._activate_conflict_detail(snapshot.status))

        await self._do_activate(db_session, snapshot)
        return await self._commit_snapshot_change(
            db_session,
            snapshot,
            concurrent_detail="Cannot activate: concurrent active snapshot conflict detected",
        )

    async def _commit_snapshot_change(
        self,
        session: AsyncSession,
        snapshot: KnowledgeSnapshot,
        *,
        concurrent_detail: str,
    ) -> KnowledgeSnapshot:
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            if not self._is_active_scope_conflict(error):
                raise
            raise SnapshotConflictError(concurrent_detail) from error

        await session.refresh(snapshot)
        return snapshot

    async def _do_activate(
        self,
        session: AsyncSession,
        snapshot: KnowledgeSnapshot,
    ) -> None:
        current_active_snapshot = await session.scalar(
            select(KnowledgeSnapshot)
            .where(
                KnowledgeSnapshot.agent_id == snapshot.agent_id,
                KnowledgeSnapshot.knowledge_base_id == snapshot.knowledge_base_id,
                KnowledgeSnapshot.status == SnapshotStatus.ACTIVE,
                KnowledgeSnapshot.id != snapshot.id,
            )
            .with_for_update()
        )
        if current_active_snapshot is not None:
            current_active_snapshot.status = SnapshotStatus.PUBLISHED

        agent = await session.scalar(
            select(Agent).where(Agent.id == snapshot.agent_id).with_for_update()
        )
        if agent is None:
            raise RuntimeError("Snapshot activation requires an existing agent")

        snapshot.status = SnapshotStatus.ACTIVE
        snapshot.activated_at = datetime.now(UTC)
        agent.active_snapshot_id = snapshot.id

    async def _count_chunks(
        self,
        session: AsyncSession,
        *,
        snapshot_id: uuid.UUID,
        status: ChunkStatus,
    ) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.snapshot_id == snapshot_id, Chunk.status == status)
            )
            or 0
        )

    async def _get_snapshot_for_update(
        self,
        session: AsyncSession,
        snapshot_id: uuid.UUID,
        *,
        agent_id: uuid.UUID | None = None,
        knowledge_base_id: uuid.UUID | None = None,
    ) -> KnowledgeSnapshot | None:
        conditions = [KnowledgeSnapshot.id == snapshot_id]
        if agent_id is not None:
            conditions.append(KnowledgeSnapshot.agent_id == agent_id)
        if knowledge_base_id is not None:
            conditions.append(KnowledgeSnapshot.knowledge_base_id == knowledge_base_id)

        return await session.scalar(
            select(KnowledgeSnapshot)
            .where(*conditions)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _activate_conflict_detail(self, status: SnapshotStatus) -> str:
        if status is SnapshotStatus.DRAFT:
            return "Cannot activate: snapshot status is 'draft', publish it first"
        if status is SnapshotStatus.ARCHIVED:
            return (
                "Cannot activate: snapshot status is 'archived', "
                "archived snapshots cannot be activated"
            )
        return f"Cannot activate: snapshot status is '{status.value}', expected 'published'"

    def _is_active_scope_conflict(self, error: IntegrityError) -> bool:
        original_error = getattr(error, "orig", None)
        constraint_name = getattr(original_error, "constraint_name", None)
        return constraint_name == "uq_one_active_per_scope"
