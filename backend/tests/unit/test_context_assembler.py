from __future__ import annotations

import uuid

from app.persona.loader import PersonaContext
from app.services.citation import SourceInfo
from app.services.context_assembler import ContextAssembler
from app.services.conversation_memory import MemoryBlock
from app.services.promotions import Promotion
from app.services.qdrant import RetrievedChunk


def _persona(
    *,
    identity: str = "I am the twin.",
    soul: str = "I speak calmly.",
    behavior: str = "I avoid politics.",
) -> PersonaContext:
    return PersonaContext(
        identity=identity,
        soul=soul,
        behavior=behavior,
        config_commit_hash="abc123",
        config_content_hash="def456",
    )


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


def _source_info(source_id: uuid.UUID, *, title: str = "Test Source") -> SourceInfo:
    return SourceInfo(id=source_id, title=title, public_url=None, source_type="pdf")


def _promo(
    *,
    title: str = "Test Promo",
    priority: str = "high",
    context: str = "When relevant.",
    body: str = "Buy this product.",
) -> Promotion:
    return Promotion(
        title=title,
        priority=priority,
        valid_from=None,
        valid_to=None,
        context=context,
        body=body,
    )


def _assembler(
    *,
    persona: PersonaContext | None = None,
    promotions: list[Promotion] | None = None,
    retrieval_context_budget: int = 4096,
    max_citations: int = 5,
    min_retrieved_chunks: int = 1,
) -> ContextAssembler:
    return ContextAssembler(
        persona_context=persona or _persona(),
        active_promotions=promotions or [],
        retrieval_context_budget=retrieval_context_budget,
        max_citations=max_citations,
        min_retrieved_chunks=min_retrieved_chunks,
    )


def _memory_block(
    *,
    summary_text: str | None = None,
    messages: list[dict[str, str]] | None = None,
    total_tokens: int = 0,
) -> MemoryBlock:
    return MemoryBlock(
        summary_text=summary_text,
        messages=messages or [],
        total_tokens=total_tokens,
        needs_summary_update=False,
        window_start_message_id=None,
    )


def test_system_message_has_xml_tags_in_order() -> None:
    chunk = _chunk("Some knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    result = _assembler(promotions=[_promo()]).assemble(
        chunks=[chunk],
        query="What?",
        source_map=source_map,
    )
    system = result.messages[0]["content"]
    assert system.index("<system_safety>") < system.index("<identity>")
    assert system.index("<identity>") < system.index("<soul>")
    assert system.index("<soul>") < system.index("<behavior>")
    assert system.index("<behavior>") < system.index("<promotions>")
    assert system.index("<promotions>") < system.index("<citation_instructions>")
    assert system.index("<citation_instructions>") < system.index("<content_guidelines>")


def test_each_tag_has_closing_tag() -> None:
    chunk = _chunk("Knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    result = _assembler(promotions=[_promo()]).assemble(
        chunks=[chunk],
        query="Q?",
        source_map=source_map,
    )
    system = result.messages[0]["content"]
    for tag in [
        "system_safety",
        "identity",
        "soul",
        "behavior",
        "promotions",
        "citation_instructions",
        "content_guidelines",
    ]:
        assert f"<{tag}>" in system
        assert f"</{tag}>" in system


def test_no_promotions_omits_tag() -> None:
    result = _assembler(promotions=[]).assemble(chunks=[_chunk("K")], query="Q?", source_map={})
    assert "<promotions>" not in result.messages[0]["content"]


def test_promotion_injected_with_content() -> None:
    result = _assembler(promotions=[_promo(body="Special offer!")]).assemble(
        chunks=[_chunk("K")],
        query="Q?",
        source_map={},
    )
    assert "Special offer!" in result.messages[0]["content"]
    assert "<promotions>" in result.messages[0]["content"]


def test_included_promotions_in_result() -> None:
    promo = _promo()
    result = _assembler(promotions=[promo]).assemble(
        chunks=[_chunk("K")],
        query="Q?",
        source_map={},
    )
    assert result.included_promotions == [promo]


def test_citation_instructions_absent_when_no_chunks() -> None:
    result = _assembler().assemble(chunks=[], query="Q?", source_map={})
    assert "<citation_instructions>" not in result.messages[0]["content"]


def test_citation_instructions_present_when_chunks_exist() -> None:
    chunk = _chunk("K")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    result = _assembler().assemble(chunks=[chunk], query="Q?", source_map=source_map)
    assert "<citation_instructions>" in result.messages[0]["content"]
    assert "[source:N]" in result.messages[0]["content"]


def test_all_chunks_fit_in_budget() -> None:
    chunks = [_chunk("short") for _ in range(3)]
    result = _assembler(retrieval_context_budget=4096).assemble(
        chunks=chunks,
        query="Q?",
        source_map={},
    )
    assert result.retrieval_chunks_used == 3
    assert result.retrieval_chunks_total == 3


def test_chunks_trimmed_when_over_budget() -> None:
    chunks = [_chunk("x" * 1000, score=0.9 - index * 0.1) for index in range(3)]
    result = _assembler(retrieval_context_budget=500).assemble(
        chunks=chunks,
        query="Q?",
        source_map={},
    )
    assert result.retrieval_chunks_used < 3
    assert result.retrieval_chunks_total == 3


def test_min_retrieved_chunks_overrides_budget() -> None:
    result = _assembler(retrieval_context_budget=100, min_retrieved_chunks=1).assemble(
        chunks=[_chunk("x" * 3000)],
        query="Q?",
        source_map={},
    )
    assert result.retrieval_chunks_used == 1


def test_zero_chunks_after_budget_with_min_zero() -> None:
    result = _assembler(retrieval_context_budget=1, min_retrieved_chunks=0).assemble(
        chunks=[_chunk("x" * 3000)],
        query="Q?",
        source_map={},
    )
    assert result.retrieval_chunks_used == 0
    assert "<knowledge_context>" not in result.messages[1]["content"]


def test_user_message_contains_query() -> None:
    result = _assembler().assemble(chunks=[_chunk("K")], query="Tell me about AI", source_map={})
    assert "Tell me about AI" in result.messages[1]["content"]
    assert "<user_query>" in result.messages[1]["content"]


def test_user_message_contains_knowledge_context_tag() -> None:
    result = _assembler().assemble(chunks=[_chunk("Knowledge text")], query="Q?", source_map={})
    assert "<knowledge_context>" in result.messages[1]["content"]
    assert "Knowledge text" in result.messages[1]["content"]


def test_empty_identity_produces_empty_tag() -> None:
    result = _assembler(persona=_persona(identity="")).assemble(
        chunks=[],
        query="Q?",
        source_map={},
    )
    system = result.messages[0]["content"]
    assert "<identity>" in system
    assert "</identity>" in system


def test_all_empty_persona_still_has_safety() -> None:
    result = _assembler(persona=_persona(identity="", soul="", behavior="")).assemble(
        chunks=[],
        query="Q?",
        source_map={},
    )
    assert "<system_safety>" in result.messages[0]["content"]


def test_token_estimate_is_positive() -> None:
    result = _assembler().assemble(chunks=[_chunk("Knowledge")], query="Question?", source_map={})
    assert result.token_estimate > 0


def test_layer_token_counts_populated() -> None:
    result = _assembler(promotions=[_promo()]).assemble(
        chunks=[_chunk("Knowledge")],
        query="Q?",
        source_map={},
    )
    assert result.layer_token_counts["system_safety"] > 0
    assert result.layer_token_counts["content_guidelines"] > 0
    assert result.layer_token_counts["user_query"] > 0


def test_memory_block_none_is_backward_compatible() -> None:
    chunk = _chunk("Knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}

    result = _assembler().assemble(
        chunks=[chunk],
        query="What?",
        source_map=source_map,
        memory_block=None,
    )

    assert len(result.messages) == 2
    assert result.messages[0]["role"] == "system"
    assert result.messages[1]["role"] == "user"
    assert "conversation_memory" not in result.layer_token_counts
    assert "<conversation_summary>" not in result.messages[0]["content"]


def test_memory_block_with_history_creates_multi_turn_messages() -> None:
    chunk = _chunk("Knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    block = _memory_block(
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        total_tokens=10,
    )

    result = _assembler().assemble(
        chunks=[chunk],
        query="What is X?",
        source_map=source_map,
        memory_block=block,
    )

    assert len(result.messages) == 4
    assert [message["role"] for message in result.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert result.messages[1]["content"] == "Hello"
    assert result.messages[2]["content"] == "Hi there!"


def test_summary_in_system_prompt_before_citation_instructions() -> None:
    chunk = _chunk("Knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    block = _memory_block(summary_text="User asked about concerts.", total_tokens=15)

    result = _assembler(promotions=[_promo()]).assemble(
        chunks=[chunk],
        query="Tell me more",
        source_map=source_map,
        memory_block=block,
    )

    system = result.messages[0]["content"]
    assert "<conversation_summary>" in system
    assert "User asked about concerts." in system
    assert system.index("<promotions>") < system.index("<conversation_summary>")
    assert system.index("<conversation_summary>") < system.index("<citation_instructions>")


def test_summary_omitted_when_absent() -> None:
    result = _assembler().assemble(
        chunks=[],
        query="Q?",
        source_map={},
        memory_block=_memory_block(summary_text=None, total_tokens=0),
    )

    assert "<conversation_summary>" not in result.messages[0]["content"]


def test_conversation_memory_token_count_is_unified() -> None:
    chunk = _chunk("Knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    block = _memory_block(
        summary_text="Earlier context.",
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ],
        total_tokens=25,
    )

    result = _assembler().assemble(
        chunks=[chunk],
        query="Q",
        source_map=source_map,
        memory_block=block,
    )

    assert result.layer_token_counts["conversation_memory"] == 25
    assert "conversation_summary" not in result.layer_token_counts


def test_history_only_memory_token_count_is_unified() -> None:
    chunk = _chunk("Knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    block = _memory_block(
        summary_text=None,
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ],
        total_tokens=14,
    )

    result = _assembler().assemble(
        chunks=[chunk],
        query="Q",
        source_map=source_map,
        memory_block=block,
    )

    assert result.layer_token_counts["conversation_memory"] == 14
    assert "conversation_summary" not in result.layer_token_counts


def test_summary_only_memory_keeps_two_message_output() -> None:
    chunk = _chunk("Knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    block = _memory_block(
        summary_text="Topics A and B.",
        messages=[],
        total_tokens=12,
    )

    result = _assembler().assemble(
        chunks=[chunk],
        query="Q",
        source_map=source_map,
        memory_block=block,
    )

    assert len(result.messages) == 2
    assert result.layer_token_counts["conversation_memory"] == 12
    assert "<conversation_summary>" in result.messages[0]["content"]
