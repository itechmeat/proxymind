from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import DeadlineExceeded, ServiceUnavailable
from google.cloud import documentai_v1 as documentai
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.db.models.enums import SourceType
from app.services.document_processing import ParsedBlock, TextChunker, normalize_whitespace

if TYPE_CHECKING:
    from app.services.document_processing import ChunkData


class DocumentAIParser:
    def __init__(
        self,
        *,
        project_id: str | None,
        location: str,
        processor_id: str | None,
        chunk_max_tokens: int,
        client: documentai.DocumentProcessorServiceClient | None = None,
    ) -> None:
        if not project_id or not processor_id:
            raise ValueError("Document AI project_id and processor_id are required")

        self._client = client or documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        )
        self._processor_name = self._client.processor_path(project_id, location, processor_id)
        self._chunker = TextChunker(chunk_max_tokens=chunk_max_tokens)

    async def parse_and_chunk(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[ChunkData]:
        if source_type is not SourceType.PDF:
            raise ValueError("DocumentAIParser supports PDF sources only")

        document = await self._process_document(content)
        return self._chunker.chunk_blocks(self._extract_blocks(document))

    async def _process_document(self, content: bytes) -> documentai.Document:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((ServiceUnavailable, DeadlineExceeded)),
            reraise=True,
        ):
            with attempt:
                return await asyncio.to_thread(self._process_document_sync, content)

        raise RuntimeError("Document AI retry loop ended unexpectedly")

    def _process_document_sync(self, content: bytes) -> documentai.Document:
        result = self._client.process_document(
            request=documentai.ProcessRequest(
                name=self._processor_name,
                raw_document=documentai.RawDocument(
                    content=content,
                    mime_type="application/pdf",
                ),
            )
        )
        return result.document

    def _extract_blocks(self, document: documentai.Document) -> list[ParsedBlock]:
        document_text = getattr(document, "text", "") or ""
        blocks: list[ParsedBlock] = []
        current_chapter: str | None = None
        current_section: str | None = None

        for page in getattr(document, "pages", []):
            page_number = int(getattr(page, "page_number", 0) or 0) or None
            paragraphs = list(getattr(page, "paragraphs", []))
            layouts = paragraphs or list(getattr(page, "blocks", []))

            for item in layouts:
                layout = getattr(item, "layout", None)
                if layout is None:
                    continue

                text = normalize_whitespace(self._extract_anchor_text(document_text, layout.text_anchor))
                if not text:
                    continue

                heading_level = self._heading_level(text)
                if heading_level == 1:
                    current_chapter = text
                    current_section = None
                    continue
                if heading_level == 2:
                    if current_chapter is None:
                        current_chapter = text
                    else:
                        current_section = text
                    continue

                headings = tuple(
                    heading
                    for heading in (current_chapter, current_section)
                    if heading is not None
                )
                blocks.append(
                    ParsedBlock(
                        text=text,
                        headings=headings,
                        anchor_page=page_number,
                    )
                )

        if blocks:
            return blocks

        fallback_text = normalize_whitespace(document_text)
        if not fallback_text:
            return []

        return [ParsedBlock(text=fallback_text, headings=(), anchor_page=1)]

    @staticmethod
    def _extract_anchor_text(document_text: str, text_anchor: Any) -> str:
        segments = list(getattr(text_anchor, "text_segments", []) or [])
        parts: list[str] = []
        for segment in segments:
            start_index = int(getattr(segment, "start_index", 0) or 0)
            end_index = int(getattr(segment, "end_index", 0) or 0)
            if end_index <= start_index:
                continue
            parts.append(document_text[start_index:end_index])
        return "".join(parts)

    @staticmethod
    def _heading_level(text: str) -> int | None:
        words = text.split()
        if not words or len(words) > 12 or len(text) > 100:
            return None
        if text.endswith((".", "!", "?", ";")):
            return None
        if text.isupper():
            if len(words) == 1 and len(text) < 8:
                return None
            return 1
        if text.istitle() or text.endswith(":"):
            return 2
        return None
