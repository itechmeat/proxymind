from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from app.db.models.enums import SourceType
from app.services.document_processing import (
    ChunkData,
    ParsedBlock,
    TextChunker,
    normalize_whitespace,
)

_WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_MAX_DOCX_XML_BYTES = 8 * 1024 * 1024
_MAX_DOCX_XML_COMPRESSION_RATIO = 100


class _HTMLBlockParser(HTMLParser):
    _HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    _TEXT_BLOCK_TAGS = {"p", "li", "td", "th"}
    _SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[ParsedBlock] = []
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
            heading_text = normalize_whitespace(" ".join(self._buffer))
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
        if self._active_heading_level is None and self._active_block_tag is None:
            return
        self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush_buffer()

    def _flush_buffer(self) -> None:
        text = normalize_whitespace(" ".join(self._buffer))
        self._buffer = []
        if not text or self._active_heading_level is not None:
            return
        self.blocks.append(ParsedBlock(text=text, headings=_current_headings(self._heading_stack)))


class LightweightParser:
    def __init__(self, *, chunk_max_tokens: int) -> None:
        self._chunker = TextChunker(chunk_max_tokens=chunk_max_tokens)

    async def parse_and_chunk(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[ChunkData]:
        del filename
        if not content.strip():
            return []

        blocks = await asyncio.to_thread(self._convert_document, content, source_type)
        if not blocks:
            return []

        return await asyncio.to_thread(self._chunker.chunk_blocks, blocks)

    def _convert_document(
        self,
        content: bytes,
        source_type: SourceType,
    ) -> list[ParsedBlock]:
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
        raise ValueError(f"Unsupported source type for LightweightParser: {source_type.value}")

    @staticmethod
    def _parse_markdown(text: str) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        heading_stack: list[str | None] = [None] * 6
        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            paragraph = normalize_whitespace(" ".join(paragraph_lines))
            paragraph_lines.clear()
            if paragraph:
                blocks.append(ParsedBlock(text=paragraph, headings=_current_headings(heading_stack)))

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
    def _parse_plain_text(text: str) -> list[ParsedBlock]:
        normalized = normalize_whitespace(text)
        if not normalized:
            return []
        return [ParsedBlock(text=normalized, headings=())]

    @staticmethod
    def _parse_html(text: str) -> list[ParsedBlock]:
        parser = _HTMLBlockParser()
        parser.feed(text)
        parser.close()
        return parser.blocks

    @staticmethod
    def _parse_docx(content: bytes) -> list[ParsedBlock]:
        try:
            with ZipFile(BytesIO(content)) as archive:
                document_info = archive.getinfo("word/document.xml")
                _validate_zip_member(
                    document_info.file_size,
                    document_info.compress_size,
                    max_size=_MAX_DOCX_XML_BYTES,
                    max_ratio=_MAX_DOCX_XML_COMPRESSION_RATIO,
                )
                document_xml = archive.read(document_info)
        except (BadZipFile, KeyError) as error:
            raise ValueError("Invalid DOCX file") from error

        root = ElementTree.fromstring(document_xml)
        blocks: list[ParsedBlock] = []
        heading_stack: list[str | None] = [None] * 6

        body = root.find("w:body", _WORD_NAMESPACE)
        if body is None:
            return []

        for paragraph in body.findall(".//w:p", _WORD_NAMESPACE):
            text = normalize_whitespace(
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
            blocks.append(ParsedBlock(text=text, headings=_current_headings(heading_stack)))

        return blocks

    @staticmethod
    def _parse_pdf(content: bytes) -> list[ParsedBlock]:
        reader = PdfReader(BytesIO(content))
        blocks: list[ParsedBlock] = []
        for page_index, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            for paragraph in _split_text_blocks(page_text):
                blocks.append(ParsedBlock(text=paragraph, headings=(), anchor_page=page_index))
        return blocks


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
    paragraphs = [normalize_whitespace(part) for part in text.replace("\r", "\n").split("\n\n")]
    return [paragraph for paragraph in paragraphs if paragraph]


def _validate_zip_member(
    file_size: int,
    compressed_size: int,
    *,
    max_size: int,
    max_ratio: int,
) -> None:
    if file_size > max_size:
        raise ValueError("DOCX file is too large to parse safely")
    if compressed_size > 0 and (file_size / compressed_size) > max_ratio:
        raise ValueError("DOCX file compression ratio is too high")
