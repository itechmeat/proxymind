from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.db.models.enums import SourceType

if TYPE_CHECKING:
    pass

def _input_format_for_source_type(source_type: SourceType) -> Any | None:
    from docling.datamodel.base_models import InputFormat

    # TXT is handled separately via convert_string() because Docling consumes
    # plain text most reliably as Markdown content rather than a binary stream.
    return {
        SourceType.MARKDOWN: InputFormat.MD,
        SourceType.PDF: InputFormat.PDF,
        SourceType.DOCX: InputFormat.DOCX,
        SourceType.HTML: InputFormat.HTML,
    }.get(source_type)


def _suffix_for_input_format(input_format: Any) -> str:
    from docling.datamodel.base_models import InputFormat

    return {
        InputFormat.MD: ".md",
        InputFormat.PDF: ".pdf",
        InputFormat.DOCX: ".docx",
        InputFormat.HTML: ".html",
    }[input_format]


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
        converter: Any | None = None,
        chunker: Any | None = None,
    ) -> None:
        from docling.chunking import HybridChunker
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

        self._converter = converter or DocumentConverter(
            allowed_formats=[
                InputFormat.MD,
                InputFormat.PDF,
                InputFormat.DOCX,
                InputFormat.HTML,
            ]
        )
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
    ) -> Any | None:
        from docling.datamodel.base_models import DocumentStream, InputFormat

        input_format = _input_format_for_source_type(source_type)

        if input_format is InputFormat.MD:
            stream = DocumentStream(
                name=self._normalize_stream_name(filename, input_format),
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

        if input_format in {InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML}:
            stream = DocumentStream(
                name=self._normalize_stream_name(filename, input_format),
                stream=BytesIO(content),
            )
            return self._converter.convert(stream).document

        raise ValueError(f"Unsupported source type for DoclingParser: {source_type.value}")

    def _chunk_document(self, document: Any) -> list[ChunkData]:
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
    def _normalize_stream_name(filename: str, input_format: Any) -> str:
        path = Path(filename)
        expected_suffix = _suffix_for_input_format(input_format)
        if path.suffix.lower() == expected_suffix:
            return path.name
        return f"{path.stem or 'document'}{expected_suffix}"

    @staticmethod
    def _extract_anchor_page(chunk: Any) -> int | None:
        for item in getattr(chunk.meta, "doc_items", []):
            for prov in getattr(item, "prov", []):
                page_no = getattr(prov, "page_no", None)
                if isinstance(page_no, int):
                    return page_no
        return None
