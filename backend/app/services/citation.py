from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.services.qdrant import RetrievedChunk

_CITATION_PATTERN = re.compile(r"\[source:(\d+)\]")


@dataclass(slots=True, frozen=True)
class SourceInfo:
    id: uuid.UUID
    title: str
    public_url: str | None
    source_type: str


@dataclass(slots=True, frozen=True)
class Citation:
    index: int
    source_id: uuid.UUID
    source_title: str
    source_type: str
    url: str | None
    anchor: dict[str, int | str | None]
    text_citation: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Citation:
        return cls(
            index=value["index"],
            source_id=uuid.UUID(str(value["source_id"])),
            source_title=value["source_title"],
            source_type=value["source_type"],
            url=value.get("url"),
            anchor=dict(value.get("anchor") or {}),
            text_citation=value["text_citation"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "source_id": str(self.source_id),
            "source_title": self.source_title,
            "source_type": self.source_type,
            "url": self.url,
            "anchor": self.anchor,
            "text_citation": self.text_citation,
        }


def _build_text_citation(title: str, anchor: dict[str, int | str | None]) -> str:
    parts = [f'"{title}"']
    chapter = anchor.get("chapter")
    section = anchor.get("section")
    page = anchor.get("page")
    timecode = anchor.get("timecode")

    if chapter is not None:
        parts.append(str(chapter))
    if section is not None:
        parts.append(str(section))
    if page is not None:
        parts.append(f"p. {page}")

    text_citation = ", ".join(parts)
    if timecode:
        text_citation += f" at {timecode}"
    return text_citation


class CitationService:
    @staticmethod
    def extract(
        content: str,
        chunks: list[RetrievedChunk],
        source_map: dict[uuid.UUID, SourceInfo],
        max_citations: int,
    ) -> list[Citation]:
        if max_citations <= 0:
            return []

        citations: list[Citation] = []
        seen_source_ids: set[uuid.UUID] = set()

        for match in _CITATION_PATTERN.finditer(content):
            index = int(match.group(1))
            if index < 1 or index > len(chunks):
                continue

            chunk = chunks[index - 1]
            if chunk.source_id in seen_source_ids:
                continue

            source_info = source_map.get(chunk.source_id)
            if source_info is None:
                continue

            seen_source_ids.add(chunk.source_id)
            anchor = {
                "page": chunk.anchor_metadata.get("anchor_page"),
                "chapter": chunk.anchor_metadata.get("anchor_chapter"),
                "section": chunk.anchor_metadata.get("anchor_section"),
                "timecode": chunk.anchor_metadata.get("anchor_timecode"),
            }
            citations.append(
                Citation(
                    index=index,
                    source_id=chunk.source_id,
                    source_title=source_info.title,
                    source_type=source_info.source_type,
                    url=source_info.public_url,
                    anchor=anchor,
                    text_citation=_build_text_citation(source_info.title, anchor),
                )
            )
            if len(citations) >= max_citations:
                break

        return citations
