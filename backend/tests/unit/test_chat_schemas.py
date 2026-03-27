from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.chat_schemas import MessageInHistory, MessageResponse
from app.db.models.enums import MessageRole, MessageStatus


def _message_with_citations(citations: list[dict[str, object]] | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid7(),
        session_id=uuid.uuid7(),
        role=MessageRole.ASSISTANT,
        content="answer",
        status=MessageStatus.COMPLETE,
        citations=citations,
        products=None,
        model_name="openai/gpt-4o",
        token_count_prompt=10,
        token_count_completion=20,
        created_at=datetime.now(UTC),
    )


def test_message_response_skips_malformed_citations() -> None:
    message = _message_with_citations(
        [
            {
                "index": 1,
                "source_id": str(uuid.uuid7()),
                "source_title": "Valid Source",
                "source_type": "pdf",
                "url": None,
                "anchor": {"page": 1},
                "text_citation": '"Valid Source", p. 1',
            },
            {"source_title": "broken"},
            {
                "index": 2,
                "source_id": "not-a-uuid",
                "source_title": "Broken UUID",
                "source_type": "pdf",
                "text_citation": "bad",
            },
        ]
    )

    response = MessageResponse.from_message(message, retrieved_chunks_count=1)

    assert response.citations is not None
    assert len(response.citations) == 1
    assert response.citations[0].source_title == "Valid Source"


def test_message_history_skips_malformed_citations() -> None:
    message = _message_with_citations(
        [
            {"source_title": "broken"},
            {
                "index": 1,
                "source_id": str(uuid.uuid7()),
                "source_title": "History Source",
                "source_type": "pdf",
                "url": None,
                "anchor": {"chapter": "Chapter 1"},
                "text_citation": '"History Source", Chapter 1',
            },
        ]
    )

    response = MessageInHistory.from_message(message)

    assert response.citations is not None
    assert len(response.citations) == 1
    assert response.citations[0].source_title == "History Source"


def test_message_response_parses_purchase_fields_and_products() -> None:
    message = _message_with_citations(
        [
            {
                "index": 1,
                "source_id": str(uuid.uuid7()),
                "source_title": "Valid Source",
                "source_type": "pdf",
                "url": None,
                "anchor": {"page": 1},
                "text_citation": '"Valid Source", p. 1',
                "purchase_url": "https://store.example.com/book",
                "purchase_title": "AI in Practice",
                "catalog_item_type": "book",
            }
        ]
    )
    message.products = [
        {
            "index": 1,
            "catalog_item_id": str(uuid.uuid7()),
            "name": "AI in Practice",
            "sku": "AI-PRACTICE-2026",
            "item_type": "book",
            "url": "https://store.example.com/book",
            "image_url": None,
            "text_recommendation": "AI in Practice (book)",
        }
    ]

    response = MessageResponse.from_message(message, retrieved_chunks_count=1)

    assert response.citations is not None
    assert response.citations[0].purchase_url == "https://store.example.com/book"
    assert response.products is not None
    assert response.products[0].sku == "AI-PRACTICE-2026"
