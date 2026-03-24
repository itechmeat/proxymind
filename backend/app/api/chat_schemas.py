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
    idempotency_key: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("text must not be empty")
            return normalized
        return value


class AnchorResponse(BaseModel):
    page: int | None = None
    chapter: str | None = None
    section: str | None = None
    timecode: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> AnchorResponse:
        return cls.model_validate(value or {})


class CitationResponse(BaseModel):
    index: int
    source_id: uuid.UUID
    source_title: str
    source_type: str
    url: str | None = None
    anchor: AnchorResponse
    text_citation: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CitationResponse:
        return cls(
            index=value["index"],
            source_id=uuid.UUID(str(value["source_id"])),
            source_title=value["source_title"],
            source_type=value["source_type"],
            url=value.get("url"),
            anchor=AnchorResponse.from_dict(value.get("anchor")),
            text_citation=value["text_citation"],
        )


_REQUIRED_CITATION_FIELDS = {
    "index",
    "source_id",
    "source_title",
    "source_type",
    "text_citation",
}


def _parse_citations(value: list[dict[str, Any]] | None) -> list[CitationResponse] | None:
    if value is None:
        return None

    citations: list[CitationResponse] = []
    for item in value:
        if not isinstance(item, dict) or not _REQUIRED_CITATION_FIELDS.issubset(item):
            continue
        try:
            citations.append(CitationResponse.from_dict(item))
        except (TypeError, ValueError):
            continue

    return citations


class MessageResponse(BaseModel):
    message_id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    citations: list[CitationResponse] | None = None
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
            citations=_parse_citations(message.citations),
            model_name=message.model_name,
            retrieved_chunks_count=retrieved_chunks_count,
            token_count_prompt=message.token_count_prompt,
            token_count_completion=message.token_count_completion,
            created_at=message.created_at,
        )


class MessageInHistory(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    citations: list[CitationResponse] | None = None
    model_name: str | None
    created_at: datetime

    @classmethod
    def from_message(cls, message: Message) -> MessageInHistory:
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            status=message.status,
            citations=_parse_citations(message.citations),
            model_name=message.model_name,
            created_at=message.created_at,
        )


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
