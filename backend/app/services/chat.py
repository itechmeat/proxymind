from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Message, Session
from app.db.models.enums import MessageRole, MessageStatus, SessionChannel, SessionStatus
from app.persona.loader import PersonaContext
from app.services.llm import LLMService
from app.services.prompt import NO_CONTEXT_REFUSAL, build_chat_prompt
from app.services.qdrant import RetrievedChunk
from app.services.retrieval import RetrievalService
from app.services.snapshot import SnapshotService

FAILED_ASSISTANT_CONTENT = "Failed to generate assistant response."


class SessionNotFoundError(RuntimeError):
    pass


class NoActiveSnapshotError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ChatAnswerResult:
    assistant_message: Message
    retrieved_chunks_count: int


class ChatService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        snapshot_service: SnapshotService,
        retrieval_service: RetrievalService,
        llm_service: LLMService,
        persona_context: PersonaContext,
        min_retrieved_chunks: int,
    ) -> None:
        self._session = session
        self._snapshot_service = snapshot_service
        self._retrieval_service = retrieval_service
        self._llm_service = llm_service
        self._persona_context = persona_context
        self._min_retrieved_chunks = min_retrieved_chunks
        self._logger = structlog.get_logger(__name__)

    async def create_session(
        self,
        *,
        channel: SessionChannel = SessionChannel.WEB,
    ) -> Session:
        active_snapshot = await self._snapshot_service.get_active_snapshot(
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )
        chat_session = Session(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            snapshot_id=active_snapshot.id if active_snapshot is not None else None,
            status=SessionStatus.ACTIVE,
            message_count=0,
            channel=channel,
        )
        self._session.add(chat_session)
        await self._session.commit()
        await self._session.refresh(chat_session)
        self._logger.info(
            "chat.session_created",
            session_id=str(chat_session.id),
            channel=chat_session.channel.value,
            snapshot_id=str(chat_session.snapshot_id) if chat_session.snapshot_id else None,
        )
        return chat_session

    async def answer(
        self,
        *,
        session_id: uuid.UUID,
        text: str,
    ) -> ChatAnswerResult:
        chat_session = await self._load_session(session_id)
        snapshot_id = await self._ensure_snapshot_binding(chat_session)

        await self._persist_message(
            chat_session,
            role=MessageRole.USER,
            content=text,
            status=MessageStatus.RECEIVED,
            snapshot_id=snapshot_id,
        )
        self._logger.info(
            "chat.user_message_saved",
            session_id=str(chat_session.id),
            snapshot_id=str(snapshot_id),
        )

        retrieved_chunks: list[RetrievedChunk] = []
        try:
            retrieved_chunks = await self._retrieval_service.search(text, snapshot_id=snapshot_id)
            self._logger.info(
                "chat.retrieval_completed",
                session_id=str(chat_session.id),
                snapshot_id=str(snapshot_id),
                retrieved_chunks_count=len(retrieved_chunks),
            )
            if len(retrieved_chunks) < self._min_retrieved_chunks:
                assistant_message = await self._persist_message(
                    chat_session,
                    role=MessageRole.ASSISTANT,
                    content=NO_CONTEXT_REFUSAL,
                    status=MessageStatus.COMPLETE,
                    snapshot_id=snapshot_id,
                    source_ids=[],
                )
                self._logger.info(
                    "chat.refusal_returned",
                    session_id=str(chat_session.id),
                    snapshot_id=str(snapshot_id),
                    retrieved_chunks_count=len(retrieved_chunks),
                    min_retrieved_chunks=self._min_retrieved_chunks,
                    config_commit_hash=self._persona_context.config_commit_hash,
                    config_content_hash=self._persona_context.config_content_hash,
                )
                return ChatAnswerResult(
                    assistant_message=assistant_message,
                    retrieved_chunks_count=len(retrieved_chunks),
                )

            self._logger.info(
                "chat.llm_requested",
                session_id=str(chat_session.id),
                snapshot_id=str(snapshot_id),
                retrieved_chunks_count=len(retrieved_chunks),
            )
            llm_response = await self._llm_service.complete(
                build_chat_prompt(text, retrieved_chunks, self._persona_context)
            )
            source_ids = self._deduplicate_source_ids(retrieved_chunks)
            assistant_message = await self._persist_message(
                chat_session,
                role=MessageRole.ASSISTANT,
                content=llm_response.content,
                status=MessageStatus.COMPLETE,
                snapshot_id=snapshot_id,
                source_ids=source_ids,
                model_name=llm_response.model_name,
                token_count_prompt=llm_response.token_count_prompt,
                token_count_completion=llm_response.token_count_completion,
            )
            self._logger.info(
                "chat.assistant_completed",
                session_id=str(chat_session.id),
                snapshot_id=str(snapshot_id),
                retrieved_chunks_count=len(retrieved_chunks),
                model_name=llm_response.model_name,
                config_commit_hash=self._persona_context.config_commit_hash,
                config_content_hash=self._persona_context.config_content_hash,
            )
            return ChatAnswerResult(
                assistant_message=assistant_message,
                retrieved_chunks_count=len(retrieved_chunks),
            )
        except Exception as error:
            try:
                await self._persist_message(
                    chat_session,
                    role=MessageRole.ASSISTANT,
                    content=FAILED_ASSISTANT_CONTENT,
                    status=MessageStatus.FAILED,
                    snapshot_id=snapshot_id,
                    source_ids=self._deduplicate_source_ids(retrieved_chunks),
                )
            except Exception as persistence_error:
                self._logger.error(
                    "chat.failed_message_persist_failed",
                    session_id=str(chat_session.id),
                    snapshot_id=str(snapshot_id),
                    error=str(persistence_error),
                )
            self._logger.error(
                "chat.answer_failed",
                session_id=str(chat_session.id),
                snapshot_id=str(snapshot_id),
                retrieved_chunks_count=len(retrieved_chunks),
                error=str(error),
            )
            raise error

    async def get_session(self, session_id: uuid.UUID) -> Session:
        return await self._load_session(session_id, include_messages=True)

    async def _load_session(
        self,
        session_id: uuid.UUID,
        *,
        include_messages: bool = False,
    ) -> Session:
        statement = select(Session).where(Session.id == session_id)
        if include_messages:
            statement = statement.options(selectinload(Session.messages))

        chat_session = await self._session.scalar(statement)
        if chat_session is None:
            raise SessionNotFoundError("Session not found")
        return chat_session

    async def _ensure_snapshot_binding(self, chat_session: Session) -> uuid.UUID:
        if chat_session.snapshot_id is not None:
            return chat_session.snapshot_id

        active_snapshot = await self._snapshot_service.get_active_snapshot(
            agent_id=chat_session.agent_id,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )
        if active_snapshot is None:
            self._logger.warning(
                "chat.lazy_bind_failed",
                session_id=str(chat_session.id),
            )
            raise NoActiveSnapshotError("No active snapshot is available")

        chat_session.snapshot_id = active_snapshot.id
        await self._session.commit()
        await self._session.refresh(chat_session)
        self._logger.info(
            "chat.lazy_bind_succeeded",
            session_id=str(chat_session.id),
            snapshot_id=str(active_snapshot.id),
        )
        return active_snapshot.id

    async def _persist_message(
        self,
        chat_session: Session,
        *,
        role: MessageRole,
        content: str,
        status: MessageStatus,
        snapshot_id: uuid.UUID | None,
        source_ids: list[uuid.UUID] | None = None,
        model_name: str | None = None,
        token_count_prompt: int | None = None,
        token_count_completion: int | None = None,
    ) -> Message:
        message = Message(
            id=uuid.uuid7(),
            session_id=chat_session.id,
            role=role,
            content=content,
            status=status,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
        )
        chat_session.message_count += 1
        self._session.add(message)
        await self._session.commit()
        await self._session.refresh(message)
        return message

    @staticmethod
    def _deduplicate_source_ids(chunks: list[RetrievedChunk]) -> list[uuid.UUID]:
        seen: set[uuid.UUID] = set()
        source_ids: list[uuid.UUID] = []
        for chunk in chunks:
            if chunk.source_id in seen:
                continue
            seen.add(chunk.source_id)
            source_ids.append(chunk.source_id)
        return source_ids
