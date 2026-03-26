from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.services.token_counter import CHARS_PER_TOKEN, ApproximateTokenizer

if TYPE_CHECKING:
    from app.db.models.enums import SourceType


@dataclass(slots=True, frozen=True)
class ParsedBlock:
    text: str
    headings: tuple[str, ...]
    anchor_page: int | None = None


@dataclass(slots=True, frozen=True)
class ChunkData:
    text_content: str
    token_count: int
    chunk_index: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None = None


class DocumentProcessor(Protocol):
    async def parse_and_chunk(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[ChunkData]: ...


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


class TextChunker:
    def __init__(self, *, chunk_max_tokens: int) -> None:
        self._chunk_max_tokens = chunk_max_tokens
        self._tokenizer = ApproximateTokenizer()

    def chunk_blocks(self, blocks: list[ParsedBlock]) -> list[ChunkData]:
        chunk_data: list[ChunkData] = []
        current_parts: list[str] = []
        current_tokens = 0
        current_headings: tuple[str, ...] = ()
        current_anchor_page: int | None = None

        def flush() -> None:
            nonlocal current_parts, current_tokens, current_headings, current_anchor_page
            text_content = normalize_whitespace("\n\n".join(current_parts))
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
            block_text = normalize_whitespace(block.text)
            if not block_text:
                continue
            if current_parts and block.headings != current_headings:
                flush()
            for fragment in self._split_block_text(block_text):
                fragment_tokens = self._tokenizer.count_tokens(fragment)
                if current_parts and current_tokens + fragment_tokens > self._chunk_max_tokens:
                    flush()
                if not current_parts:
                    current_headings = block.headings
                    current_anchor_page = block.anchor_page
                current_parts.append(fragment)
                current_tokens += fragment_tokens

        flush()
        return chunk_data

    def _split_block_text(self, text: str) -> list[str]:
        if self._tokenizer.count_tokens(text) <= self._chunk_max_tokens:
            return [text]

        max_chars = max(CHARS_PER_TOKEN, self._chunk_max_tokens * CHARS_PER_TOKEN)
        fragments: list[str] = []
        start = 0

        while start < len(text):
            end = min(len(text), start + max_chars)
            if end < len(text):
                split_at = text.rfind(" ", start, end)
                if split_at <= start:
                    split_at = end
            else:
                split_at = end

            fragment = text[start:split_at].strip()
            if fragment:
                fragments.append(fragment)
            start = split_at
            while start < len(text) and text[start].isspace():
                start += 1

        return fragments
