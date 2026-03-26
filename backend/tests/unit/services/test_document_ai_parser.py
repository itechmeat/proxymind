from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.api_core.exceptions import DeadlineExceeded, InvalidArgument, ServiceUnavailable

from app.db.models.enums import SourceType
from app.services.document_ai_parser import DocumentAIParser


def _segment(start: int, end: int) -> SimpleNamespace:
    return SimpleNamespace(start_index=start, end_index=end)


def _layout(start: int, end: int) -> SimpleNamespace:
    return SimpleNamespace(text_anchor=SimpleNamespace(text_segments=[_segment(start, end)]))


def _document(*texts: str) -> SimpleNamespace:
    joined = "\n".join(texts)
    cursor = 0
    paragraphs = []
    for text in texts:
        start = cursor
        end = start + len(text)
        paragraphs.append(SimpleNamespace(layout=_layout(start, end)))
        cursor = end + 1
    return SimpleNamespace(
        text=joined,
        pages=[SimpleNamespace(page_number=1, paragraphs=paragraphs)],
    )


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def processor_path(self, project_id: str, location: str, processor_id: str) -> str:
        return f"projects/{project_id}/locations/{location}/processors/{processor_id}"

    def process_document(self, *, request) -> SimpleNamespace:
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(document=response)


@pytest.mark.asyncio
async def test_document_ai_parser_normalizes_chunks() -> None:
    client = _FakeClient([_document("INTRODUCTION", "Background", "Alpha beta gamma")])
    parser = DocumentAIParser(
        project_id="project",
        location="us",
        processor_id="processor",
        chunk_max_tokens=50,
        client=client,
    )

    chunks = await parser.parse_and_chunk(b"pdf", "report.pdf", SourceType.PDF)

    assert len(chunks) == 1
    assert chunks[0].text_content == "Alpha beta gamma"
    assert chunks[0].anchor_page == 1
    assert chunks[0].anchor_chapter == "INTRODUCTION"
    assert chunks[0].anchor_section == "Background"
    assert chunks[0].anchor_timecode is None


@pytest.mark.asyncio
async def test_document_ai_parser_returns_empty_when_document_has_no_text() -> None:
    client = _FakeClient([SimpleNamespace(text="", pages=[])])
    parser = DocumentAIParser(
        project_id="project",
        location="us",
        processor_id="processor",
        chunk_max_tokens=50,
        client=client,
    )

    chunks = await parser.parse_and_chunk(b"pdf", "report.pdf", SourceType.PDF)

    assert chunks == []


@pytest.mark.asyncio
async def test_document_ai_parser_retries_transient_errors() -> None:
    client = _FakeClient(
        [
            ServiceUnavailable("try again"),
            _document("INTRODUCTION", "Alpha beta gamma"),
        ]
    )
    parser = DocumentAIParser(
        project_id="project",
        location="us",
        processor_id="processor",
        chunk_max_tokens=50,
        client=client,
    )

    chunks = await parser.parse_and_chunk(b"pdf", "report.pdf", SourceType.PDF)

    assert len(chunks) == 1
    assert client.calls == 2


@pytest.mark.asyncio
async def test_document_ai_parser_retries_deadline_exceeded() -> None:
    client = _FakeClient(
        [
            DeadlineExceeded("timed out"),
            _document("INTRODUCTION", "Alpha beta gamma"),
        ]
    )
    parser = DocumentAIParser(
        project_id="project",
        location="us",
        processor_id="processor",
        chunk_max_tokens=50,
        client=client,
    )

    chunks = await parser.parse_and_chunk(b"pdf", "report.pdf", SourceType.PDF)

    assert len(chunks) == 1
    assert client.calls == 2


@pytest.mark.asyncio
async def test_document_ai_parser_propagates_after_retry_exhaustion() -> None:
    client = _FakeClient(
        [
            ServiceUnavailable("try again"),
            ServiceUnavailable("try again"),
            ServiceUnavailable("try again"),
        ]
    )
    parser = DocumentAIParser(
        project_id="project",
        location="us",
        processor_id="processor",
        chunk_max_tokens=50,
        client=client,
    )

    with pytest.raises(ServiceUnavailable):
        await parser.parse_and_chunk(b"pdf", "report.pdf", SourceType.PDF)

    assert client.calls == 3


@pytest.mark.asyncio
async def test_document_ai_parser_does_not_retry_non_transient_errors() -> None:
    client = _FakeClient([InvalidArgument("bad request")])
    parser = DocumentAIParser(
        project_id="project",
        location="us",
        processor_id="processor",
        chunk_max_tokens=50,
        client=client,
    )

    with pytest.raises(InvalidArgument):
        await parser.parse_and_chunk(b"pdf", "report.pdf", SourceType.PDF)

    assert client.calls == 1


@pytest.mark.asyncio
async def test_document_ai_parser_keeps_short_all_caps_content() -> None:
    client = _FakeClient([_document("NOTE", "Alpha beta gamma")])
    parser = DocumentAIParser(
        project_id="project",
        location="us",
        processor_id="processor",
        chunk_max_tokens=50,
        client=client,
    )

    chunks = await parser.parse_and_chunk(b"pdf", "report.pdf", SourceType.PDF)

    assert len(chunks) == 1
    assert chunks[0].text_content == "NOTE Alpha beta gamma"
    assert chunks[0].anchor_chapter is None
