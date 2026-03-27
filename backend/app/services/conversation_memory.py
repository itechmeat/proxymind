from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.token_counter import estimate_tokens


class SessionLike(Protocol):
    id: uuid.UUID
    summary: str | None
    summary_token_count: int | None
    summary_up_to_message_id: uuid.UUID | None


class MessageLike(Protocol):
    id: uuid.UUID
    role: Any
    content: str


@dataclass(slots=True, frozen=True)
class MemoryBlock:
    summary_text: str | None
    messages: list[dict[str, str]]
    total_tokens: int
    needs_summary_update: bool
    window_start_message_id: uuid.UUID | None


class ConversationMemoryService:
    def __init__(self, *, budget: int, summary_ratio: float) -> None:
        self._budget = budget
        self._summary_ratio = summary_ratio

    def build_memory_block(
        self,
        *,
        session: SessionLike,
        messages: list[MessageLike],
    ) -> MemoryBlock:
        if not messages:
            return MemoryBlock(
                summary_text=None,
                messages=[],
                total_tokens=0,
                needs_summary_update=False,
                window_start_message_id=None,
            )

        summary_text = session.summary
        summary_tokens = self._resolve_summary_tokens(session)
        recent_messages = messages

        if session.summary_up_to_message_id is not None:
            boundary_index = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if message.id == session.summary_up_to_message_id
                ),
                None,
            )
            if boundary_index is None:
                summary_text = None
                summary_tokens = 0
            else:
                recent_messages = messages[boundary_index + 1 :]
        else:
            summary_text = None
            summary_tokens = 0

        window_budget = max(0, self._budget - summary_tokens)
        selected_messages: list[MessageLike] = []
        used_tokens = 0

        for message in reversed(recent_messages):
            message_tokens = estimate_tokens(message.content)
            if used_tokens + message_tokens > window_budget:
                break
            selected_messages.append(message)
            used_tokens += message_tokens

        selected_messages.reverse()
        window_start_message_id = selected_messages[0].id if selected_messages else None
        needs_summary_update = len(selected_messages) != len(recent_messages)

        return MemoryBlock(
            summary_text=summary_text,
            messages=[
                {
                    "role": self._role_value(message.role),
                    "content": message.content,
                }
                for message in selected_messages
            ],
            total_tokens=summary_tokens + used_tokens,
            needs_summary_update=needs_summary_update,
            window_start_message_id=window_start_message_id,
        )

    @staticmethod
    def _resolve_summary_tokens(session: SessionLike) -> int:
        if session.summary is None:
            return 0
        if session.summary_token_count is not None:
            return max(0, session.summary_token_count)
        return estimate_tokens(session.summary)

    @staticmethod
    def _role_value(role: Any) -> str:
        value = getattr(role, "value", role)
        return str(value)
