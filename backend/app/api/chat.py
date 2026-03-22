from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.api.chat_schemas import (
    CreateSessionRequest,
    MessageResponse,
    SendMessageRequest,
    SessionResponse,
    SessionWithMessagesResponse,
)
from app.api.dependencies import get_chat_service
from app.services.chat import ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _raise_chat_http_error(error: Exception) -> None:
    from app.services.chat import NoActiveSnapshotError, SessionNotFoundError

    if isinstance(error, SessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, NoActiveSnapshotError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    payload: CreateSessionRequest | None = Body(default=None),
) -> SessionResponse:
    session = await chat_service.create_session(
        channel=(payload or CreateSessionRequest()).channel
    )
    return SessionResponse.from_session(session)


@router.post("/messages", response_model=MessageResponse)
async def send_message(
    payload: SendMessageRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> MessageResponse:
    try:
        result = await chat_service.answer(
            session_id=payload.session_id,
            text=payload.text,
        )
    except Exception as error:
        _raise_chat_http_error(error)

    return MessageResponse.from_message(
        result.assistant_message,
        retrieved_chunks_count=result.retrieved_chunks_count,
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
