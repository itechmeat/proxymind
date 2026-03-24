from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.chat_schemas import (
    CreateSessionRequest,
    SendMessageRequest,
    SessionResponse,
    SessionWithMessagesResponse,
)
from app.api.dependencies import get_chat_service, get_sse_settings
from app.services.chat import (
    ChatService,
    ChatStreamCitations,
    ChatStreamDone,
    ChatStreamError,
    ChatStreamMeta,
    ChatStreamToken,
    ConcurrentStreamError,
    IdempotencyConflictError,
    NoActiveSnapshotError,
    SessionNotFoundError,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _raise_chat_http_error(error: Exception) -> NoReturn:
    if isinstance(error, SessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, NoActiveSnapshotError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, (ConcurrentStreamError, IdempotencyConflictError)):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise error


def _format_sse(event_type: str, data: dict[str, object]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    payload: CreateSessionRequest | None = Body(default=None),
) -> SessionResponse:
    session = await chat_service.create_session(channel=(payload or CreateSessionRequest()).channel)
    return SessionResponse.from_session(session)


@router.post("/messages")
async def send_message(
    request: Request,
    payload: SendMessageRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    sse_settings: Annotated[dict[str, int], Depends(get_sse_settings)],
) -> StreamingResponse:
    heartbeat_interval = sse_settings["heartbeat_interval"]
    inter_token_timeout = sse_settings["inter_token_timeout"]

    try:
        event_stream = chat_service.stream_answer(
            session_id=payload.session_id,
            text=payload.text,
            idempotency_key=payload.idempotency_key,
        )
        first_event = await anext(event_stream)
    except StopAsyncIteration:
        raise HTTPException(status_code=500, detail="Empty stream")
    except Exception as error:
        _raise_chat_http_error(error)

    assistant_message_id: uuid.UUID | None = None
    accumulated_content: list[str] = []

    def format_event(
        event: ChatStreamMeta | ChatStreamToken | ChatStreamDone | ChatStreamError | ChatStreamCitations,
    ) -> str:
        nonlocal assistant_message_id
        if isinstance(event, ChatStreamMeta):
            assistant_message_id = event.message_id
            return _format_sse(
                "meta",
                {
                    "message_id": str(event.message_id),
                    "session_id": str(event.session_id),
                    "snapshot_id": str(event.snapshot_id) if event.snapshot_id else None,
                },
            )
        if isinstance(event, ChatStreamToken):
            accumulated_content.append(event.content)
            return _format_sse("token", {"content": event.content})
        if isinstance(event, ChatStreamCitations):
            return _format_sse(
                "citations",
                {"citations": [citation.to_dict() for citation in event.citations]},
            )
        if isinstance(event, ChatStreamDone):
            return _format_sse(
                "done",
                {
                    "token_count_prompt": event.token_count_prompt,
                    "token_count_completion": event.token_count_completion,
                    "model_name": event.model_name,
                    "retrieved_chunks_count": event.retrieved_chunks_count,
                },
            )
        return _format_sse("error", {"detail": event.detail})

    async def generate() -> AsyncIterator[str]:
        nonlocal assistant_message_id
        yield format_event(first_event)

        iterator = event_stream.__aiter__()
        deadline = time.monotonic() + inter_token_timeout
        try:
            while True:
                remaining_until_timeout = deadline - time.monotonic()
                wait_time = min(heartbeat_interval, remaining_until_timeout)
                if wait_time <= 0:
                    yield _format_sse("error", {"detail": "LLM response timed out"})
                    if assistant_message_id is not None:
                        await chat_service.save_failed_on_timeout(
                            assistant_message_id,
                            "".join(accumulated_content),
                        )
                    return

                try:
                    next_event = await asyncio.wait_for(iterator.__anext__(), timeout=wait_time)
                except TimeoutError:
                    if remaining_until_timeout <= heartbeat_interval:
                        yield _format_sse("error", {"detail": "LLM response timed out"})
                        if assistant_message_id is not None:
                            await chat_service.save_failed_on_timeout(
                                assistant_message_id,
                                "".join(accumulated_content),
                            )
                        return
                    yield ": heartbeat\n\n"
                    continue
                except StopAsyncIteration:
                    return

                deadline = time.monotonic() + inter_token_timeout
                yield format_event(next_event)
        except asyncio.CancelledError:
            if assistant_message_id is not None:
                await chat_service.save_partial_on_disconnect(
                    assistant_message_id,
                    "".join(accumulated_content),
                )
            raise

    return StreamingResponse(
        generate(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}", response_model=SessionWithMessagesResponse)
async def get_session(
    session_id: uuid.UUID,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> SessionWithMessagesResponse:
    try:
        session = await chat_service.get_session(session_id)
    except Exception as error:
        _raise_chat_http_error(error)

    return SessionWithMessagesResponse.from_session(session)
