from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from docling.chunking import HybridChunker
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc import DoclingDocument

from app.db.models.enums import SourceType


@dataclass(slots=True, frozen=True)
class ChunkData:
    text_content: str
    token_count: int
    chunk_index: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None = None


class DoclingParser:
    def __init__(
        self,
        *,
        chunk_max_tokens: int,
        converter: DocumentConverter | None = None,
        chunker: HybridChunker | None = None,
    ) -> None:
        self._converter = converter or DocumentConverter(allowed_formats=[InputFormat.MD])
        self._chunker = chunker or HybridChunker(
            tokenizer=HuggingFaceTokenizer.from_pretrained(
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                max_tokens=chunk_max_tokens,
            )
        )

    async def parse_and_chunk(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[ChunkData]:
        if not content.strip():
            return []

        document = await asyncio.to_thread(self._convert_document, content, filename, source_type)
        if document is None:
            return []

        return await asyncio.to_thread(self._chunk_document, document)

    def _convert_document(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> DoclingDocument | None:
        if source_type is SourceType.MARKDOWN:
            stream = DocumentStream(
                name=self._normalize_markdown_name(filename),
                stream=BytesIO(content),
            )
            return self._converter.convert(stream).document

        if source_type is SourceType.TXT:
            text = content.decode("utf-8", errors="replace")
            if not text.strip():
                return None
            normalized_name = f"{Path(filename).stem or 'document'}.md"
            return self._converter.convert_string(
                text,
                format=InputFormat.MD,
                name=normalized_name,
            ).document

        raise ValueError(f"Unsupported source type for DoclingParser: {source_type.value}")

    def _chunk_document(self, document: DoclingDocument) -> list[ChunkData]:
        chunk_data: list[ChunkData] = []
        for chunk in self._chunker.chunk(document):
            text_content = chunk.text.strip()
            if not text_content:
                continue

            headings = list(chunk.meta.headings or [])
            chunk_data.append(
                ChunkData(
                    text_content=text_content,
                    token_count=self._chunker.tokenizer.count_tokens(
                        self._chunker.contextualize(chunk)
                    ),
                    chunk_index=len(chunk_data),
                    anchor_page=self._extract_anchor_page(chunk),
                    anchor_chapter=headings[0] if headings else None,
                    anchor_section=headings[-1] if len(headings) > 1 else None,
                )
            )
        return chunk_data

    @staticmethod
    def _normalize_markdown_name(filename: str) -> str:
        path = Path(filename)
        if path.suffix.lower() == ".md":
            return path.name
        return f"{path.stem or 'document'}.md"

    @staticmethod
    def _extract_anchor_page(chunk: Any) -> int | None:
        for item in getattr(chunk.meta, "doc_items", []):
            for prov in getattr(item, "prov", []):
                page_no = getattr(prov, "page_no", None)
                if isinstance(page_no, int):
                    return page_no
        return None
