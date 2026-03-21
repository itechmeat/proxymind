from __future__ import annotations

import uuid

from app.services.prompt import SYSTEM_PROMPT, build_chat_prompt
from app.services.qdrant import RetrievedChunk


def _chunk(text: str, *, source_id: uuid.UUID | None = None, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text,
        score=score,
        anchor_metadata={
            "anchor_page": 1,
            "anchor_chapter": "Chapter",
            "anchor_section": "Section",
            "anchor_timecode": None,
        },
    )


def test_build_chat_prompt_includes_system_instruction_and_context() -> None:
    chunk = _chunk("Context body")

    messages = build_chat_prompt("What is this?", [chunk])

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1]["role"] == "user"
    assert "Knowledge context:" in messages[1]["content"]
    assert "Context body" in messages[1]["content"]
    assert str(chunk.source_id) in messages[1]["content"]
    assert "Question:\nWhat is this?" in messages[1]["content"]


def test_build_chat_prompt_supports_multiple_chunks() -> None:
    first = _chunk("First context")
    second = _chunk("Second context")

    messages = build_chat_prompt("Summarize it", [first, second])

    assert "First context" in messages[1]["content"]
    assert "Second context" in messages[1]["content"]
    assert str(first.source_id) in messages[1]["content"]
    assert str(second.source_id) in messages[1]["content"]


def test_build_chat_prompt_omits_context_block_for_empty_chunks() -> None:
    messages = build_chat_prompt("Only question", [])

    assert messages == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Question:\nOnly question"},
    ]
