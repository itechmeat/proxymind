from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Message, Session
from app.db.models.enums import MessageRole, MessageStatus
from app.services.token_counter import estimate_tokens
from app.workers.observability import observe_background_job

logger = structlog.get_logger(__name__)

SUMMARIZE_SYSTEM_PROMPT_TEMPLATE = (
    "Summarize the following conversation between a user and an AI assistant. "
    "Preserve: key topics discussed, user's questions and intent, important facts mentioned, "
    "any decisions or conclusions reached. Keep summary under {max_summary_tokens} tokens. "
    "Be concise but complete. Write in the same language as the conversation."
)


async def generate_session_summary(
    ctx: dict[str, Any],
    session_id: str,
    window_start_message_id: str | None,
    *,
    correlation_id: str | None = None,
) -> None:
    session_factory = ctx["session_factory"]
    summary_llm_service = ctx["summary_llm_service"]
    settings = ctx["settings"]
    worker_redis_client = ctx.get("worker_redis_client")

    if not isinstance(session_factory, async_sessionmaker):
        raise RuntimeError("Worker context is missing a valid session factory")

    async with observe_background_job(
        task_name="generate_session_summary",
        correlation_id=correlation_id,
        redis_client=worker_redis_client,
    ):
        try:
            session_uuid = uuid.UUID(session_id)
            window_start_uuid = (
                None if window_start_message_id is None else uuid.UUID(window_start_message_id)
            )
        except ValueError:
            logger.warning(
                "worker.summary.invalid_ids",
                session_id=session_id,
                window_start_message_id=window_start_message_id,
            )
            return

        async with session_factory() as session:
            chat_session = await session.get(Session, session_uuid)
            if chat_session is None:
                logger.warning("worker.summary.session_missing", session_id=session_id)
                return

            result = await session.execute(
                select(Message)
                .where(
                    Message.session_id == session_uuid,
                    Message.status.in_([MessageStatus.RECEIVED, MessageStatus.COMPLETE]),
                )
                .order_by(Message.created_at)
            )
            history = list(result.scalars().all())

            if not history:
                logger.info("worker.summary.empty_history", session_id=session_id)
                return

            if window_start_uuid is None:
                window_start_index = len(history)
            else:
                window_start_index = next(
                    (
                        index
                        for index, message in enumerate(history)
                        if message.id == window_start_uuid
                    ),
                    None,
                )
                if window_start_index is None:
                    logger.warning(
                        "worker.summary.window_start_missing",
                        session_id=session_id,
                        window_start_message_id=window_start_message_id,
                    )
                    return

            boundary_index = None
            original_boundary_id = chat_session.summary_up_to_message_id
            if chat_session.summary_up_to_message_id is not None:
                boundary_index = next(
                    (
                        index
                        for index, message in enumerate(history)
                        if message.id == chat_session.summary_up_to_message_id
                    ),
                    None,
                )

            start_index = 0 if boundary_index is None else boundary_index + 1
            messages_to_summarize = history[start_index:window_start_index]

            if not messages_to_summarize:
                # If the summary boundary already moved past this window start,
                # another task has effectively won the race and summarized this range.
                # Returning here is the task-level dedup guard described in the spec.
                logger.info("worker.summary.no_messages_to_summarize", session_id=session_id)
                return

            prompt_messages = _build_summary_prompt(
                existing_summary=chat_session.summary if boundary_index is not None else None,
                messages=messages_to_summarize,
                max_summary_tokens=max(
                    1,
                    int(settings.conversation_memory_budget * settings.conversation_summary_ratio),
                ),
            )

            try:
                response = await asyncio.wait_for(
                    summary_llm_service.complete(
                        prompt_messages,
                        temperature=settings.conversation_summary_temperature,
                    ),
                    timeout=settings.conversation_summary_timeout_ms / 1000,
                )
            except Exception as error:
                logger.warning(
                    "worker.summary.generation_failed",
                    session_id=session_id,
                    error=error.__class__.__name__,
                )
                return

            summary_text = response.content.strip()
            if not summary_text:
                logger.warning("worker.summary.empty_response", session_id=session_id)
                return

            last_summarized_message_id = messages_to_summarize[-1].id
            try:
                summary_token_count = estimate_tokens(summary_text)
                result = await session.execute(
                    update(Session)
                    .where(Session.id == session_uuid)
                    .where(
                        Session.summary_up_to_message_id.is_(None)
                        if original_boundary_id is None
                        else Session.summary_up_to_message_id == original_boundary_id
                    )
                    .values(
                        summary=summary_text,
                        summary_token_count=summary_token_count,
                        summary_up_to_message_id=last_summarized_message_id,
                    )
                )
                if result.rowcount != 1:
                    await session.rollback()
                    logger.info("worker.summary.stale_boundary", session_id=session_id)
                    return

                chat_session.summary = summary_text
                chat_session.summary_token_count = summary_token_count
                chat_session.summary_up_to_message_id = last_summarized_message_id
                await session.commit()
            except Exception as error:
                await session.rollback()
                logger.warning(
                    "worker.summary.persistence_failed",
                    session_id=session_id,
                    error=error.__class__.__name__,
                )


def _build_summary_prompt(
    *,
    existing_summary: str | None,
    messages: list[Message],
    max_summary_tokens: int,
) -> list[dict[str, str]]:
    prompt_lines: list[str] = []
    if existing_summary:
        prompt_lines.append(f"Previous summary: {existing_summary}")
        prompt_lines.append("")
        prompt_lines.append("New messages to incorporate:")

    for message in messages:
        role_name = "User" if message.role is MessageRole.USER else "Assistant"
        prompt_lines.append(f"{role_name}: {message.content}")

    return [
        {
            "role": "system",
            "content": SUMMARIZE_SYSTEM_PROMPT_TEMPLATE.format(
                max_summary_tokens=max_summary_tokens,
            ),
        },
        {"role": "user", "content": "\n".join(prompt_lines)},
    ]
