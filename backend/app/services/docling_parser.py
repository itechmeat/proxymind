from __future__ import annotations

import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from app.db.models.enums import SourceType

from app.services.token_counter import ApproximateTokenizer

_WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


@dataclass(slots=True, frozen=True)
class _ParsedBlock:
    text: str
    headings: tuple[str, ...]
    anchor_page: int | None = None


class _HTMLBlockParser(HTMLParser):
    _HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    _TEXT_BLOCK_TAGS = {"p", "li", "td", "th"}
    _SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[_ParsedBlock] = []
        self._heading_stack: list[str | None] = [None] * 6
        self._active_heading_level: int | None = None
        self._active_block_tag: str | None = None
        self._buffer: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized_tag = tag.lower()
        if normalized_tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if normalized_tag in self._HEADING_LEVELS:
            self._flush_buffer()
            self._active_heading_level = self._HEADING_LEVELS[normalized_tag]
            self._buffer = []
            return
        if normalized_tag in self._TEXT_BLOCK_TAGS:
            self._flush_buffer()
            self._active_block_tag = normalized_tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if normalized_tag in self._HEADING_LEVELS and self._active_heading_level is not None:
            heading_text = _normalize_whitespace(" ".join(self._buffer))
            self._buffer = []
            if heading_text:
                level_index = self._active_heading_level - 1
                self._heading_stack[level_index] = heading_text
                for deeper_index in range(level_index + 1, len(self._heading_stack)):
                    self._heading_stack[deeper_index] = None
            self._active_heading_level = None
            return
        if normalized_tag == self._active_block_tag:
            self._flush_buffer()
            self._active_block_tag = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush_buffer()

    def _flush_buffer(self) -> None:
        text = _normalize_whitespace(" ".join(self._buffer))
        self._buffer = []
        if not text or self._active_heading_level is not None:
            return
        self.blocks.append(_ParsedBlock(text=text, headings=_current_headings(self._heading_stack)))


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
        chunker: Any | None = None,
    ) -> None:
        self._chunk_max_tokens = chunk_max_tokens
        self._tokenizer = ApproximateTokenizer()
        self._chunker = chunker

    async def parse_and_chunk(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[ChunkData]:
        if not content.strip():
            return []

        document = await asyncio.to_thread(self._convert_document, content, filename, source_type)
        if not document:
            return []

        return await asyncio.to_thread(self._chunk_document, document)

    def _convert_document(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[_ParsedBlock]:
        if source_type is SourceType.MARKDOWN:
            return self._parse_markdown(content.decode("utf-8", errors="replace"))
        if source_type is SourceType.TXT:
            return self._parse_plain_text(content.decode("utf-8", errors="replace"))
        if source_type is SourceType.HTML:
            return self._parse_html(content.decode("utf-8", errors="replace"))
        if source_type is SourceType.DOCX:
            return self._parse_docx(content)
        if source_type is SourceType.PDF:
            return self._parse_pdf(content)
        raise ValueError(f"Unsupported source type for DoclingParser: {source_type.value}")

    def _chunk_document(self, document: Any) -> list[ChunkData]:
        if self._chunker is not None and hasattr(self._chunker, "chunk"):
            return self._chunk_external_document(document)
        return self._chunk_blocks(document)

    def _chunk_external_document(self, document: Any) -> list[ChunkData]:
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

    def _chunk_blocks(self, blocks: list[_ParsedBlock]) -> list[ChunkData]:
        chunk_data: list[ChunkData] = []
        current_parts: list[str] = []
        current_tokens = 0
        current_headings: tuple[str, ...] = ()
        current_anchor_page: int | None = None

        def flush() -> None:
            nonlocal current_parts, current_tokens, current_headings, current_anchor_page
            text_content = _normalize_whitespace("\n\n".join(current_parts))
            if not text_content:
                current_parts = []
                current_tokens = 0
                current_headings = ()
                current_anchor_page = None
                return
            chunk_data.append(
                ChunkData(
                    text_content=text_content,
                    token_count=max(1, current_tokens),
                    chunk_index=len(chunk_data),
                    anchor_page=current_anchor_page,
                    anchor_chapter=current_headings[0] if current_headings else None,
                    anchor_section=current_headings[-1] if len(current_headings) > 1 else None,
                )
            )
            current_parts = []
            current_tokens = 0
            current_headings = ()
            current_anchor_page = None

        for block in blocks:
            block_text = _normalize_whitespace(block.text)
            if not block_text:
                continue
            block_tokens = self._tokenizer.count_tokens(block_text)
            if current_parts and current_tokens + block_tokens > self._chunk_max_tokens:
                flush()
            if not current_parts:
                current_headings = block.headings
                current_anchor_page = block.anchor_page
            current_parts.append(block_text)
            current_tokens += block_tokens

        flush()
        return chunk_data

    @staticmethod
    def _parse_markdown(text: str) -> list[_ParsedBlock]:
        blocks: list[_ParsedBlock] = []
        heading_stack: list[str | None] = [None] * 6
        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            paragraph = _normalize_whitespace(" ".join(paragraph_lines))
            paragraph_lines.clear()
            if paragraph:
                blocks.append(_ParsedBlock(text=paragraph, headings=_current_headings(heading_stack)))

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                continue
            if line.startswith("#"):
                flush_paragraph()
                hashes, _, title = line.partition(" ")
                level = min(len(hashes), 6)
                heading_stack[level - 1] = title.strip()
                for deeper_index in range(level, len(heading_stack)):
                    heading_stack[deeper_index] = None
                continue
            paragraph_lines.append(line)

        flush_paragraph()
        return blocks

    @staticmethod
    def _parse_plain_text(text: str) -> list[_ParsedBlock]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return []
        return [_ParsedBlock(text=normalized, headings=())]

    @staticmethod
    def _parse_html(text: str) -> list[_ParsedBlock]:
        parser = _HTMLBlockParser()
        parser.feed(text)
        parser.close()
        return parser.blocks

    @staticmethod
    def _parse_docx(content: bytes) -> list[_ParsedBlock]:
        try:
            with ZipFile(BytesIO(content)) as archive:
                document_xml = archive.read("word/document.xml")
        except (BadZipFile, KeyError) as error:
            raise ValueError("Invalid DOCX file") from error

        root = ElementTree.fromstring(document_xml)
        blocks: list[_ParsedBlock] = []
        heading_stack: list[str | None] = [None] * 6

        body = root.find("w:body", _WORD_NAMESPACE)
        if body is None:
            return []

        for paragraph in body.findall(".//w:p", _WORD_NAMESPACE):
            text = _normalize_whitespace(
                " ".join(node.text or "" for node in paragraph.findall(".//w:t", _WORD_NAMESPACE))
            )
            if not text:
                continue
            style = paragraph.find("w:pPr/w:pStyle", _WORD_NAMESPACE)
            style_value = style.get(f"{{{_WORD_NAMESPACE['w']}}}val", "") if style is not None else ""
            level = _docx_heading_level(style_value)
            if level is not None:
                heading_stack[level - 1] = text
                for deeper_index in range(level, len(heading_stack)):
                    heading_stack[deeper_index] = None
                continue
            blocks.append(_ParsedBlock(text=text, headings=_current_headings(heading_stack)))

        return blocks

    @staticmethod
    def _parse_pdf(content: bytes) -> list[_ParsedBlock]:
        reader = PdfReader(BytesIO(content))
        blocks: list[_ParsedBlock] = []
        for page_index, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            for paragraph in _split_text_blocks(page_text):
                blocks.append(_ParsedBlock(text=paragraph, headings=(), anchor_page=page_index))
        return blocks

    @staticmethod
    def _extract_anchor_page(chunk: Any) -> int | None:
        for item in getattr(chunk.meta, "doc_items", []):
            for prov in getattr(item, "prov", []):
                page_no = getattr(prov, "page_no", None)
                if isinstance(page_no, int):
                    return page_no
        return None


def _current_headings(heading_stack: list[str | None]) -> tuple[str, ...]:
    return tuple(heading for heading in heading_stack if heading)


def _docx_heading_level(style_value: str) -> int | None:
    lowered = style_value.lower()
    if lowered == "title":
        return 1
    if lowered.startswith("heading"):
        suffix = lowered.removeprefix("heading")
        if suffix.isdigit():
            return max(1, min(int(suffix), 6))
    return None


def _split_text_blocks(text: str) -> list[str]:
    paragraphs = [
        _normalize_whitespace(part)
        for part in text.replace("\r", "\n").split("\n\n")
    ]
    return [paragraph for paragraph in paragraphs if paragraph]


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())
