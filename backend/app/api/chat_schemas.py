from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import Message, Session
from app.db.models.enums import MessageRole, MessageStatus, SessionChannel, SessionStatus


class CreateSessionRequest(BaseModel):
    channel: SessionChannel = SessionChannel.WEB


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID | None
    status: SessionStatus
    channel: SessionChannel
    message_count: int
    created_at: datetime

    @classmethod
    def from_session(cls, session: Session) -> SessionResponse:
        return cls.model_validate(session)


class SendMessageRequest(BaseModel):
    session_id: uuid.UUID
    text: str = Field(min_length=1)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("text must not be empty")
            return normalized
        return value


class MessageResponse(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    model_name: str | None
    retrieved_chunks_count: int
    token_count_prompt: int | None
    token_count_completion: int | None
    created_at: datetime

    @classmethod
    def from_message(
        cls,
        message: Message,
        *,
        retrieved_chunks_count: int,
    ) -> MessageResponse:
        return cls(
            message_id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            status=message.status,
            model_name=message.model_name,
            retrieved_chunks_count=retrieved_chunks_count,
            token_count_prompt=message.token_count_prompt,
            token_count_completion=message.token_count_completion,
            created_at=message.created_at,
        )


class MessageInHistory(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    model_name: str | None
    created_at: datetime

    @classmethod
    def from_message(cls, message: Message) -> MessageInHistory:
        return cls.model_validate(message)


class SessionWithMessagesResponse(SessionResponse):
    messages: list[MessageInHistory]

    @classmethod
    def from_session(cls, session: Session) -> SessionWithMessagesResponse:
        return cls(
            id=session.id,
            snapshot_id=session.snapshot_id,
            status=session.status,
            channel=session.channel,
            message_count=session.message_count,
            created_at=session.created_at,
            messages=[MessageInHistory.from_message(message) for message in session.messages],
        )
