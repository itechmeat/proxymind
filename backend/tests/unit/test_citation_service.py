from __future__ import annotations

import uuid

from app.services.citation import CitationService, SourceInfo
from app.services.qdrant import RetrievedChunk


def _source_info(
    source_id: uuid.UUID,
    title: str = "Test Source",
    public_url: str | None = None,
    source_type: str = "pdf",
) -> SourceInfo:
    return SourceInfo(
        id=source_id,
        title=title,
        public_url=public_url,
        source_type=source_type,
    )


def _chunk(
    source_id: uuid.UUID,
    text: str = "chunk text",
    anchor_page: int | None = None,
    anchor_chapter: str | None = None,
    anchor_section: str | None = None,
    anchor_timecode: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id,
        text_content=text,
        score=0.9,
        anchor_metadata={
            "anchor_page": anchor_page,
            "anchor_chapter": anchor_chapter,
            "anchor_section": anchor_section,
            "anchor_timecode": anchor_timecode,
        },
    )


class TestCitationServiceExtract:
    def test_happy_path_single_citation(self) -> None:
        source_id = uuid.uuid4()
        chunks = [_chunk(source_id, anchor_page=42, anchor_chapter="Chapter 5")]
        source_map = {source_id: _source_info(source_id, title="Clean Architecture")}

        result = CitationService.extract(
            "According to the book [source:1], clean code matters.",
            chunks,
            source_map,
            max_citations=5,
        )

        assert len(result) == 1
        citation = result[0]
        assert citation.index == 1
        assert citation.source_id == source_id
        assert citation.source_title == "Clean Architecture"
        assert citation.url is None
        assert citation.anchor["page"] == 42
        assert citation.anchor["chapter"] == "Chapter 5"

    def test_multiple_citations(self) -> None:
        source_id_1, source_id_2 = uuid.uuid4(), uuid.uuid4()
        chunks = [_chunk(source_id_1), _chunk(source_id_2)]
        source_map = {
            source_id_1: _source_info(source_id_1, title="Source A"),
            source_id_2: _source_info(source_id_2, title="Source B"),
        }

        result = CitationService.extract(
            "First [source:1] and second [source:2].",
            chunks,
            source_map,
            max_citations=5,
        )

        assert [citation.index for citation in result] == [1, 2]

    def test_invalid_index_ignored(self) -> None:
        source_id = uuid.uuid4()
        result = CitationService.extract(
            "Valid [source:1] and invalid [source:99].",
            [_chunk(source_id)],
            {source_id: _source_info(source_id)},
            max_citations=5,
        )

        assert len(result) == 1
        assert result[0].index == 1

    def test_no_markers_returns_empty(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "No citations here.",
            [_chunk(source_id)],
            {source_id: _source_info(source_id)},
            max_citations=5,
        )

        assert result == []

    def test_markdown_link_does_not_collide_with_citation_marker(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "Read [the guide](https://example.com/guide) and compare it with [source:1].",
            [_chunk(source_id)],
            {source_id: _source_info(source_id, title="Guide")},
            max_citations=5,
        )

        assert len(result) == 1
        assert result[0].index == 1

    def test_deduplication_by_source_id(self) -> None:
        source_id = uuid.uuid4()
        result = CitationService.extract(
            "First [source:1] then [source:2].",
            [_chunk(source_id, anchor_page=10), _chunk(source_id, anchor_page=20)],
            {source_id: _source_info(source_id)},
            max_citations=5,
        )

        assert len(result) == 1
        assert result[0].anchor["page"] == 10

    def test_max_citations_truncation(self) -> None:
        source_ids = [uuid.uuid4() for _ in range(5)]
        result = CitationService.extract(
            "[source:1] [source:2] [source:3] [source:4] [source:5]",
            [_chunk(source_id) for source_id in source_ids],
            {
                source_id: _source_info(source_id, title=f"S{index}")
                for index, source_id in enumerate(source_ids)
            },
            max_citations=3,
        )

        assert [citation.index for citation in result] == [1, 2, 3]

    def test_source_not_in_map_skipped(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "Citation [source:1].",
            [_chunk(source_id)],
            {},
            max_citations=5,
        )

        assert result == []

    def test_online_source_has_url(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "See [source:1].",
            [_chunk(source_id)],
            {source_id: _source_info(source_id, public_url="https://example.com/book")},
            max_citations=5,
        )

        assert result[0].url == "https://example.com/book"

    def test_zero_index_ignored(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "Bad ref [source:0].",
            [_chunk(source_id)],
            {source_id: _source_info(source_id)},
            max_citations=5,
        )

        assert result == []


class TestTextCitation:
    def test_full_anchor(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "[source:1]",
            [
                _chunk(
                    source_id,
                    anchor_page=42,
                    anchor_chapter="Chapter 5",
                    anchor_section="Interfaces",
                )
            ],
            {source_id: _source_info(source_id, title="Clean Architecture")},
            max_citations=5,
        )

        assert result[0].text_citation == '"Clean Architecture", Chapter 5, p. 42'

    def test_title_only(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "[source:1]",
            [_chunk(source_id)],
            {source_id: _source_info(source_id, title="README")},
            max_citations=5,
        )

        assert result[0].text_citation == '"README"'

    def test_timecode_anchor(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "[source:1]",
            [_chunk(source_id, anchor_timecode="01:23:45")],
            {
                source_id: _source_info(
                    source_id,
                    title="Podcast Episode 12",
                    source_type="audio",
                )
            },
            max_citations=5,
        )

        assert result[0].text_citation == '"Podcast Episode 12" at 01:23:45'

    def test_section_used_when_chapter_missing(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "[source:1]",
            [_chunk(source_id, anchor_section="Observer")],
            {source_id: _source_info(source_id, title="Design Patterns")},
            max_citations=5,
        )

        assert result[0].text_citation == '"Design Patterns", Observer'


class TestCitationToDict:
    def test_to_dict_structure(self) -> None:
        source_id = uuid.uuid4()

        result = CitationService.extract(
            "[source:1]",
            [_chunk(source_id, anchor_page=1)],
            {source_id: _source_info(source_id, title="Test", public_url="https://x.com")},
            max_citations=5,
        )
        data = result[0].to_dict()

        assert data["index"] == 1
        assert data["source_id"] == str(source_id)
        assert data["source_title"] == "Test"
        assert data["source_type"] == "pdf"
        assert data["url"] == "https://x.com"
        assert isinstance(data["anchor"], dict)
        assert isinstance(data["text_citation"], str)
