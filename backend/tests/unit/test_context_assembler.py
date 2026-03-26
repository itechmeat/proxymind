from __future__ import annotations

import uuid

from app.persona.loader import PersonaContext
from app.services.citation import SourceInfo
from app.services.context_assembler import ContextAssembler
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


def test_system_message_has_xml_tags_in_order() -> None:
    chunk = _chunk("Some knowledge")
    source_map = {chunk.source_id: _source_info(chunk.source_id)}
    result = _assembler(promotions=[_promo()]).assemble(chunks=[chunk], query="What?", source_map=source_map)
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
    result = _assembler(promotions=[_promo()]).assemble(chunks=[chunk], query="Q?", source_map=source_map)
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
    result = _assembler(promotions=[promo]).assemble(chunks=[_chunk("K")], query="Q?", source_map={})
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
    result = _assembler(retrieval_context_budget=4096).assemble(chunks=chunks, query="Q?", source_map={})
    assert result.retrieval_chunks_used == 3
    assert result.retrieval_chunks_total == 3


def test_chunks_trimmed_when_over_budget() -> None:
    chunks = [_chunk("x" * 1000, score=0.9 - index * 0.1) for index in range(3)]
    result = _assembler(retrieval_context_budget=500).assemble(chunks=chunks, query="Q?", source_map={})
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
    result = _assembler(persona=_persona(identity="")).assemble(chunks=[], query="Q?", source_map={})
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
    result = _assembler(promotions=[_promo()]).assemble(chunks=[_chunk("Knowledge")], query="Q?", source_map={})
    assert result.layer_token_counts["system_safety"] > 0
    assert result.layer_token_counts["content_guidelines"] > 0
    assert result.layer_token_counts["user_query"] > 0
