from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import CatalogItem, Message, Session, Source
from app.db.models.enums import MessageRole, MessageStatus, SessionChannel, SessionStatus
from app.persona.loader import PersonaContext
from app.services.audit import AuditService
from app.services.citation import Citation, CitationService, SourceInfo
from app.services.content_type import compute_content_type_spans
from app.services.context_assembler import ContextAssembler
from app.services.conversation_memory import ConversationMemoryService, MemoryBlock
from app.services.llm_types import LLMToken
from app.services.metrics import CHAT_RESPONSES_TOTAL, CHAT_RESPONSE_LATENCY_SECONDS
from app.services.product_recommendation import ProductRecommendation, ProductRecommendationService
from app.services.prompt import NO_CONTEXT_REFUSAL
from app.services.qdrant import RetrievedChunk

if TYPE_CHECKING:
    from app.services.llm import LLMService
    from app.services.query_rewrite import QueryRewriteService
    from app.services.retrieval import RetrievalService
    from app.services.snapshot import SnapshotService

FAILED_ASSISTANT_CONTENT = "Failed to generate assistant response."


class SummaryEnqueuer(Protocol):
    async def __call__(
        self,
        session_id: str,
        window_start_message_id: str | None,
    ) -> None: ...


class SessionNotFoundError(RuntimeError):
    pass


class NoActiveSnapshotError(RuntimeError):
    pass


class ConcurrentStreamError(RuntimeError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ChatAnswerResult:
    assistant_message: Message
    retrieved_chunks_count: int


@dataclass(slots=True, frozen=True)
class ChatStreamMeta:
    message_id: uuid.UUID
    session_id: uuid.UUID
    snapshot_id: uuid.UUID | None


@dataclass(slots=True, frozen=True)
class ChatStreamToken:
    content: str


@dataclass(slots=True, frozen=True)
class ChatStreamDone:
    token_count_prompt: int | None
    token_count_completion: int | None
    model_name: str | None
    retrieved_chunks_count: int | None


@dataclass(slots=True, frozen=True)
class ChatStreamError:
    detail: str


@dataclass(slots=True, frozen=True)
class ChatStreamCitations:
    citations: list[Citation]


@dataclass(slots=True, frozen=True)
class ChatStreamProducts:
    products: list[ProductRecommendation]


ChatStreamEvent = (
    ChatStreamMeta
    | ChatStreamToken
    | ChatStreamDone
    | ChatStreamError
    | ChatStreamCitations
    | ChatStreamProducts
)


@dataclass(slots=True, frozen=True)
class IdempotencyCheckResult:
    user_message: Message
    replay_stream: AsyncIterator[ChatStreamEvent] | None = None


class ChatService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        snapshot_service: SnapshotService,
        retrieval_service: RetrievalService,
        llm_service: LLMService,
        query_rewrite_service: QueryRewriteService,
        context_assembler: ContextAssembler,
        min_retrieved_chunks: int,
        max_citations_per_response: int = 5,
        conversation_memory_service: ConversationMemoryService | None = None,
        summary_enqueuer: SummaryEnqueuer | None = None,
        audit_service: AuditService,
    ) -> None:
        self._session = session
        self._snapshot_service = snapshot_service
        self._retrieval_service = retrieval_service
        self._llm_service = llm_service
        self._query_rewrite_service = query_rewrite_service
        self._context_assembler = context_assembler
        self._min_retrieved_chunks = min_retrieved_chunks
        self._max_citations_per_response = max_citations_per_response
        self._conversation_memory_service = conversation_memory_service
        self._summary_enqueuer = summary_enqueuer
        self._audit_service = audit_service
        self._logger = structlog.get_logger(__name__)

    @property
    def _persona_context(self) -> PersonaContext:
        return self._context_assembler.persona_context

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
        started_at = time.perf_counter()
        chat_session = await self._load_session(session_id)
        snapshot_id = await self._ensure_snapshot_binding(chat_session)

        user_message = await self._persist_message(
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
            history = await self._load_history(chat_session.id, exclude_message_id=user_message.id)
            search_query = await self._do_rewrite(text, chat_session, user_message, history)
            memory_block = self._build_memory(chat_session, history)
            retrieved_chunks = await self._retrieval_service.search(
                search_query,
                snapshot_id=snapshot_id,
            )
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
                    citations=[],
                    parent_message_id=user_message.id,
                    config_commit_hash=self._persona_context.config_commit_hash,
                    config_content_hash=self._persona_context.config_content_hash,
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
                latency_ms = self._latency_ms(started_at)
                self._record_response_metrics(status=MessageStatus.COMPLETE, latency_ms=latency_ms)
                await self._log_audit(
                    message=assistant_message,
                    retrieval_chunks_count=len(retrieved_chunks),
                    latency_ms=latency_ms,
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
            source_map = await self._load_source_map(self._deduplicate_source_ids(retrieved_chunks))
            assembled = self._context_assembler.assemble(
                chunks=retrieved_chunks,
                query=text,
                source_map=source_map,
                memory_block=memory_block,
            )
            selected_chunks = retrieved_chunks[: assembled.retrieval_chunks_used]
            source_ids = self._deduplicate_source_ids(selected_chunks)
            llm_response = await self._llm_service.complete(assembled.messages)
            citations = CitationService.extract(
                llm_response.content,
                selected_chunks,
                source_map,
                self._max_citations_per_response,
            )
            products = ProductRecommendationService.extract(
                llm_response.content,
                assembled.catalog_items_used,
            )
            cleaned_content = ProductRecommendationService.strip_markers(llm_response.content)
            content_type_spans = [
                {"start": span.start, "end": span.end, "type": span.type}
                for span in compute_content_type_spans(
                    cleaned_content,
                    promotions=assembled.included_promotions,
                )
            ]
            assistant_message = await self._persist_message(
                chat_session,
                role=MessageRole.ASSISTANT,
                content=cleaned_content,
                status=MessageStatus.COMPLETE,
                snapshot_id=snapshot_id,
                source_ids=source_ids,
                citations=[citation.to_dict() for citation in citations],
                products=[product.to_dict() for product in products] or None,
                model_name=llm_response.model_name,
                token_count_prompt=llm_response.token_count_prompt,
                token_count_completion=llm_response.token_count_completion,
                content_type_spans=content_type_spans,
                parent_message_id=user_message.id,
                config_commit_hash=self._persona_context.config_commit_hash,
                config_content_hash=self._persona_context.config_content_hash,
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
            latency_ms = self._latency_ms(started_at)
            self._record_response_metrics(status=MessageStatus.COMPLETE, latency_ms=latency_ms)
            await self._log_audit(
                message=assistant_message,
                retrieval_chunks_count=len(selected_chunks),
                latency_ms=latency_ms,
            )
            await self._maybe_enqueue_summary(memory_block, chat_session.id)
            return ChatAnswerResult(
                assistant_message=assistant_message,
                retrieved_chunks_count=len(selected_chunks),
            )
        except Exception as error:
            failed_message: Message | None = None
            try:
                failed_message = await self._persist_message(
                    chat_session,
                    role=MessageRole.ASSISTANT,
                    content=FAILED_ASSISTANT_CONTENT,
                    status=MessageStatus.FAILED,
                    snapshot_id=snapshot_id,
                    source_ids=self._deduplicate_source_ids(retrieved_chunks),
                    parent_message_id=user_message.id,
                    config_commit_hash=self._persona_context.config_commit_hash,
                    config_content_hash=self._persona_context.config_content_hash,
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
            latency_ms = self._latency_ms(started_at)
            self._record_response_metrics(status=MessageStatus.FAILED, latency_ms=latency_ms)
            if failed_message is not None:
                await self._log_audit(
                    message=failed_message,
                    retrieval_chunks_count=len(retrieved_chunks),
                    latency_ms=latency_ms,
                )
            raise

    async def stream_answer(
        self,
        *,
        session_id: uuid.UUID,
        text: str,
        idempotency_key: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        started_at = time.perf_counter()
        chat_session = await self._load_session(session_id)
        snapshot_id = await self._ensure_snapshot_binding(chat_session)
        user_message: Message | None = None

        if idempotency_key is not None:
            idempotency_result = await self._check_idempotency(
                chat_session,
                idempotency_key=idempotency_key,
                snapshot_id=snapshot_id,
            )
            if idempotency_result is not None:
                if idempotency_result.replay_stream is not None:
                    async for event in idempotency_result.replay_stream:
                        yield event
                    return
                user_message = idempotency_result.user_message

        await self._check_no_active_stream(chat_session)

        if user_message is None:
            user_message = await self._persist_message(
                chat_session,
                role=MessageRole.USER,
                content=text,
                status=MessageStatus.RECEIVED,
                snapshot_id=snapshot_id,
                idempotency_key=idempotency_key,
            )

        retrieved_chunks: list[RetrievedChunk] = []
        try:
            history = await self._load_history(chat_session.id, exclude_message_id=user_message.id)
            search_query = await self._do_rewrite(text, chat_session, user_message, history)
            memory_block = self._build_memory(chat_session, history)
            retrieved_chunks = await self._retrieval_service.search(
                search_query,
                snapshot_id=snapshot_id,
            )
            self._logger.info(
                "chat.retrieval_completed",
                session_id=str(chat_session.id),
                snapshot_id=str(snapshot_id),
                retrieved_chunks_count=len(retrieved_chunks),
            )
        except Exception:
            await self._persist_message(
                chat_session,
                role=MessageRole.ASSISTANT,
                content=FAILED_ASSISTANT_CONTENT,
                status=MessageStatus.FAILED,
                snapshot_id=snapshot_id,
                source_ids=[],
                parent_message_id=user_message.id,
                config_commit_hash=self._persona_context.config_commit_hash,
                config_content_hash=self._persona_context.config_content_hash,
            )
            raise

        if len(retrieved_chunks) < self._min_retrieved_chunks:
            assistant_message = await self._persist_message(
                chat_session,
                role=MessageRole.ASSISTANT,
                content=NO_CONTEXT_REFUSAL,
                status=MessageStatus.COMPLETE,
                snapshot_id=snapshot_id,
                source_ids=[],
                citations=[],
                parent_message_id=user_message.id,
                config_commit_hash=self._persona_context.config_commit_hash,
                config_content_hash=self._persona_context.config_content_hash,
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
            latency_ms = self._latency_ms(started_at)
            self._record_response_metrics(status=MessageStatus.COMPLETE, latency_ms=latency_ms)
            await self._log_audit(
                message=assistant_message,
                retrieval_chunks_count=len(retrieved_chunks),
                latency_ms=latency_ms,
            )
            yield ChatStreamMeta(
                message_id=assistant_message.id,
                session_id=chat_session.id,
                snapshot_id=snapshot_id,
            )
            yield ChatStreamToken(content=NO_CONTEXT_REFUSAL)
            yield ChatStreamCitations(citations=[])
            yield ChatStreamDone(
                token_count_prompt=None,
                token_count_completion=None,
                model_name=None,
                retrieved_chunks_count=len(retrieved_chunks),
            )
            return

        source_map = await self._load_source_map(self._deduplicate_source_ids(retrieved_chunks))
        assembled = self._context_assembler.assemble(
            chunks=retrieved_chunks,
            query=text,
            source_map=source_map,
            memory_block=memory_block,
        )
        selected_chunks = retrieved_chunks[: assembled.retrieval_chunks_used]
        source_ids = self._deduplicate_source_ids(selected_chunks)
        assistant_message = await self._persist_message(
            chat_session,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.STREAMING,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            parent_message_id=user_message.id,
        )
        yield ChatStreamMeta(
            message_id=assistant_message.id,
            session_id=chat_session.id,
            snapshot_id=snapshot_id,
        )

        content_buffer: list[str] = []
        prompt = assembled.messages
        try:
            stream = self._llm_service.stream(prompt)
            if inspect.isawaitable(stream):
                stream = await stream

            async for event in stream:
                if isinstance(event, LLMToken):
                    content_buffer.append(event.content)
                    yield ChatStreamToken(content=event.content)
                    continue

                assistant_message.content = "".join(content_buffer)
                products = ProductRecommendationService.extract(
                    assistant_message.content,
                    assembled.catalog_items_used,
                )
                citations = CitationService.extract(
                    assistant_message.content,
                    selected_chunks,
                    source_map,
                    self._max_citations_per_response,
                )
                cleaned_content = ProductRecommendationService.strip_markers(
                    assistant_message.content
                )
                assistant_message.content = cleaned_content
                assistant_message.status = MessageStatus.COMPLETE
                assistant_message.model_name = event.model_name
                assistant_message.token_count_prompt = event.token_count_prompt
                assistant_message.token_count_completion = event.token_count_completion
                assistant_message.citations = [citation.to_dict() for citation in citations]
                assistant_message.products = [product.to_dict() for product in products] or None
                assistant_message.content_type_spans = [
                    {"start": span.start, "end": span.end, "type": span.type}
                    for span in compute_content_type_spans(
                        cleaned_content,
                        promotions=assembled.included_promotions,
                    )
                ]
                assistant_message.config_commit_hash = self._persona_context.config_commit_hash
                assistant_message.config_content_hash = self._persona_context.config_content_hash
                await self._session.commit()
                self._logger.info(
                    "chat.assistant_completed",
                    session_id=str(chat_session.id),
                    snapshot_id=str(snapshot_id),
                    retrieved_chunks_count=len(retrieved_chunks),
                    model_name=event.model_name,
                    config_commit_hash=self._persona_context.config_commit_hash,
                    config_content_hash=self._persona_context.config_content_hash,
                )
                latency_ms = self._latency_ms(started_at)
                self._record_response_metrics(
                    status=MessageStatus.COMPLETE,
                    latency_ms=latency_ms,
                )
                await self._log_audit(
                    message=assistant_message,
                    retrieval_chunks_count=len(selected_chunks),
                    latency_ms=latency_ms,
                )
                await self._maybe_enqueue_summary(memory_block, chat_session.id)
                yield ChatStreamCitations(citations=citations)
                if products:
                    yield ChatStreamProducts(products=products)
                yield ChatStreamDone(
                    token_count_prompt=event.token_count_prompt,
                    token_count_completion=event.token_count_completion,
                    model_name=event.model_name,
                    retrieved_chunks_count=len(selected_chunks),
                )
        except Exception as error:
            assistant_message.content = "".join(content_buffer) or FAILED_ASSISTANT_CONTENT
            assistant_message.status = MessageStatus.FAILED
            assistant_message.config_commit_hash = self._persona_context.config_commit_hash
            assistant_message.config_content_hash = self._persona_context.config_content_hash
            await self._session.commit()
            latency_ms = self._latency_ms(started_at)
            self._record_response_metrics(status=MessageStatus.FAILED, latency_ms=latency_ms)
            await self._log_audit(
                message=assistant_message,
                retrieval_chunks_count=len(retrieved_chunks),
                latency_ms=latency_ms,
            )
            self._logger.error(
                "chat.stream_failed",
                session_id=str(chat_session.id),
                snapshot_id=str(snapshot_id),
                error=str(error),
            )
            yield ChatStreamError(detail="LLM generation failed")

    async def get_session(self, session_id: uuid.UUID) -> Session:
        return await self._load_session(session_id, include_messages=True)

    async def save_partial_on_disconnect(
        self,
        assistant_message_id: uuid.UUID,
        accumulated_content: str,
    ) -> None:
        message = await self._session.get(Message, assistant_message_id)
        if message is None or message.status is not MessageStatus.STREAMING:
            return

        message.content = accumulated_content
        message.status = MessageStatus.PARTIAL
        await self._session.commit()
        latency_ms = 0
        self._record_response_metrics(status=MessageStatus.PARTIAL, latency_ms=latency_ms)
        await self._log_audit(
            message=message,
            retrieval_chunks_count=len(message.source_ids or []),
            latency_ms=latency_ms,
        )

    async def save_failed_on_timeout(
        self,
        assistant_message_id: uuid.UUID,
        accumulated_content: str,
    ) -> None:
        message = await self._session.get(Message, assistant_message_id)
        if message is None or message.status is not MessageStatus.STREAMING:
            return

        message.content = accumulated_content
        message.status = MessageStatus.FAILED
        await self._session.commit()
        latency_ms = 0
        self._record_response_metrics(status=MessageStatus.FAILED, latency_ms=latency_ms)
        await self._log_audit(
            message=message,
            retrieval_chunks_count=len(message.source_ids or []),
            latency_ms=latency_ms,
        )

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
        idempotency_key: str | None = None,
        parent_message_id: uuid.UUID | None = None,
        citations: list[dict[str, object]] | None = None,
        products: list[dict[str, object]] | None = None,
        content_type_spans: list[dict[str, object]] | None = None,
        config_commit_hash: str | None = None,
        config_content_hash: str | None = None,
    ) -> Message:
        message = Message(
            id=uuid.uuid7(),
            session_id=chat_session.id,
            parent_message_id=parent_message_id,
            role=role,
            content=content,
            status=status,
            idempotency_key=idempotency_key,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            citations=citations,
            products=products,
            content_type_spans=content_type_spans,
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
            config_commit_hash=config_commit_hash,
            config_content_hash=config_content_hash,
        )
        chat_session.message_count += 1
        self._session.add(message)
        await self._session.commit()
        await self._session.refresh(message)
        return message

    async def _load_history(
        self,
        session_id: uuid.UUID,
        exclude_message_id: uuid.UUID,
    ) -> list[Message]:
        result = await self._session.execute(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.id != exclude_message_id,
                Message.status.in_([MessageStatus.RECEIVED, MessageStatus.COMPLETE]),
            )
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def _do_rewrite(
        self,
        text: str,
        chat_session: Session,
        user_message: Message,
        history: list[Message],
    ) -> str:
        rewrite_result = await self._query_rewrite_service.rewrite(
            text,
            history,
            session_id=str(chat_session.id),
        )
        if rewrite_result.is_rewritten:
            user_message_id = str(user_message.id)
            user_message.rewritten_query = rewrite_result.query
            try:
                await self._session.commit()
                await self._session.refresh(user_message)
            except Exception as error:
                await self._session.rollback()
                await self._session.refresh(chat_session)
                await self._session.refresh(user_message)
                self._logger.warning(
                    "chat.rewrite_persist_failed",
                    error=error.__class__.__name__,
                    session_id=str(chat_session.id),
                    user_message_id=user_message_id,
                )
        return rewrite_result.query

    def _build_memory(
        self,
        chat_session: Session,
        history: list[Message],
    ) -> MemoryBlock | None:
        if self._conversation_memory_service is None:
            return None
        return self._conversation_memory_service.build_memory_block(
            session=chat_session,
            messages=history,
        )

    async def _maybe_enqueue_summary(
        self,
        memory_block: MemoryBlock | None,
        session_id: uuid.UUID,
    ) -> None:
        if (
            memory_block is None
            or not memory_block.needs_summary_update
            or self._summary_enqueuer is None
        ):
            return

        try:
            await self._summary_enqueuer(
                str(session_id),
                (
                    None
                    if memory_block.window_start_message_id is None
                    else str(memory_block.window_start_message_id)
                ),
            )
        except Exception as error:
            self._logger.warning(
                "chat.summary_enqueue_failed",
                session_id=str(session_id),
                error=str(error),
            )

    async def _log_audit(
        self,
        *,
        message: Message,
        retrieval_chunks_count: int,
        latency_ms: int | None,
    ) -> None:
        try:
            await self._audit_service.log_response(
                session_id=message.session_id,
                message_id=message.id,
                snapshot_id=message.snapshot_id,
                source_ids=message.source_ids,
                config_commit_hash=message.config_commit_hash,
                config_content_hash=message.config_content_hash,
                model_name=message.model_name,
                token_count_prompt=message.token_count_prompt,
                token_count_completion=message.token_count_completion,
                retrieval_chunks_count=retrieval_chunks_count,
                latency_ms=latency_ms,
                status=message.status.value,
            )
        except Exception as error:
            self._logger.error(
                "audit.log_failed",
                session_id=str(message.session_id) if message.session_id else None,
                message_id=str(message.id),
                error=error.__class__.__name__,
            )

    @staticmethod
    def _record_response_metrics(*, status: MessageStatus, latency_ms: int | None) -> None:
        CHAT_RESPONSES_TOTAL.labels(status=status.value).inc()
        if latency_ms is not None:
            CHAT_RESPONSE_LATENCY_SECONDS.observe(latency_ms / 1000)

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    async def _check_idempotency(
        self,
        chat_session: Session,
        *,
        idempotency_key: str,
        snapshot_id: uuid.UUID,
    ) -> IdempotencyCheckResult | None:
        existing_user_message = await self._session.scalar(
            select(Message).where(
                Message.session_id == chat_session.id,
                Message.idempotency_key == idempotency_key,
                Message.role == MessageRole.USER,
            )
        )
        if existing_user_message is None:
            return None

        assistant_message = await self._session.scalar(
            select(Message)
            .where(
                Message.parent_message_id == existing_user_message.id,
                Message.role == MessageRole.ASSISTANT,
            )
            .order_by(Message.created_at.desc())
        )
        if assistant_message is None:
            return IdempotencyCheckResult(user_message=existing_user_message)

        if assistant_message.status is MessageStatus.STREAMING:
            raise IdempotencyConflictError("A stream is already in progress for this request")
        if assistant_message.status is MessageStatus.COMPLETE:
            return IdempotencyCheckResult(
                user_message=existing_user_message,
                replay_stream=self._replay_complete(assistant_message, chat_session, snapshot_id),
            )
        return IdempotencyCheckResult(user_message=existing_user_message)

    @staticmethod
    def _replay_complete(
        assistant_message: Message,
        chat_session: Session,
        snapshot_id: uuid.UUID,
    ) -> AsyncIterator[ChatStreamEvent]:
        async def replay() -> AsyncIterator[ChatStreamEvent]:
            yield ChatStreamMeta(
                message_id=assistant_message.id,
                session_id=chat_session.id,
                snapshot_id=snapshot_id,
            )
            yield ChatStreamToken(content=assistant_message.content)
            required_citation_fields = {
                "index",
                "source_id",
                "source_title",
                "source_type",
                "text_citation",
            }
            replay_citations = [
                Citation.from_dict(citation)
                for citation in (assistant_message.citations or [])
                if required_citation_fields.issubset(citation)
            ]
            yield ChatStreamCitations(citations=replay_citations)
            required_product_fields = {
                "index",
                "catalog_item_id",
                "name",
                "sku",
                "item_type",
                "text_recommendation",
            }
            replay_products = [
                ProductRecommendation.from_dict(product)
                for product in (assistant_message.products or [])
                if required_product_fields.issubset(product)
            ]
            if replay_products:
                yield ChatStreamProducts(products=replay_products)
            yield ChatStreamDone(
                token_count_prompt=assistant_message.token_count_prompt,
                token_count_completion=assistant_message.token_count_completion,
                model_name=assistant_message.model_name,
                retrieved_chunks_count=len(assistant_message.source_ids or []),
            )

        return replay()

    async def _check_no_active_stream(self, chat_session: Session) -> None:
        # Lock the session row to prevent TOCTOU race between check and STREAMING creation
        await self._session.scalar(
            select(Session).where(Session.id == chat_session.id).with_for_update()
        )
        active_stream = await self._session.scalar(
            select(Message).where(
                Message.session_id == chat_session.id,
                Message.role == MessageRole.ASSISTANT,
                Message.status == MessageStatus.STREAMING,
            )
        )
        if active_stream is not None:
            raise ConcurrentStreamError("A stream is already active in this session")

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

    async def _load_source_map(self, source_ids: list[uuid.UUID]) -> dict[uuid.UUID, SourceInfo]:
        if not source_ids:
            return {}

        rows = await self._session.execute(
            select(
                Source.id,
                Source.title,
                Source.public_url,
                Source.source_type,
                CatalogItem.id.label("catalog_item_id"),
                CatalogItem.url.label("catalog_item_url"),
                CatalogItem.name.label("catalog_item_name"),
                CatalogItem.item_type.label("catalog_item_type"),
                CatalogItem.is_active.label("catalog_item_is_active"),
                CatalogItem.valid_from.label("catalog_item_valid_from"),
                CatalogItem.valid_until.label("catalog_item_valid_until"),
                CatalogItem.deleted_at.label("catalog_item_deleted_at"),
            )
            .outerjoin(CatalogItem, Source.catalog_item_id == CatalogItem.id)
            .where(
                Source.id.in_(source_ids),
                Source.deleted_at.is_(None),
            )
        )
        return {
            row.id: SourceInfo(
                id=row.id,
                title=row.title,
                public_url=row.public_url,
                source_type=row.source_type.value,
                catalog_item_url=row.catalog_item_url,
                catalog_item_name=row.catalog_item_name,
                catalog_item_type=(
                    row.catalog_item_type.value if row.catalog_item_type is not None else None
                ),
                catalog_item_active=self._is_catalog_item_active(
                    is_active=row.catalog_item_is_active,
                    valid_from=row.catalog_item_valid_from,
                    valid_until=row.catalog_item_valid_until,
                    deleted_at=row.catalog_item_deleted_at,
                ),
            )
            for row in rows
        }

    @staticmethod
    def _is_catalog_item_active(
        *,
        is_active: bool | None,
        valid_from: datetime | None,
        valid_until: datetime | None,
        deleted_at: datetime | None,
    ) -> bool:
        if not is_active or deleted_at is not None:
            return False

        today = datetime.now(UTC).date()
        valid_from_date = valid_from.date() if valid_from is not None else None
        valid_until_date = valid_until.date() if valid_until is not None else None
        if valid_from_date is not None and valid_from_date > today:
            return False
        if valid_until_date is not None and valid_until_date < today:
            return False
        return True
