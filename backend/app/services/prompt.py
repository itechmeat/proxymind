from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.services.qdrant import RetrievedChunk

if TYPE_CHECKING:
    from app.services.citation import SourceInfo

NO_CONTEXT_REFUSAL = "I could not find an answer to that in the knowledge base."


def _format_anchor_parts(
    *,
    title: str | None,
    anchor_metadata: dict[str, int | str | None],
) -> list[str]:
    parts: list[str] = []
    if title:
        parts.append(f'title: "{title}"')
    if anchor_metadata.get("anchor_chapter"):
        parts.append(f'chapter: "{anchor_metadata["anchor_chapter"]}"')
    if anchor_metadata.get("anchor_section"):
        parts.append(f'section: "{anchor_metadata["anchor_section"]}"')
    if anchor_metadata.get("anchor_page") is not None:
        parts.append(f'page: {anchor_metadata["anchor_page"]}')
    if anchor_metadata.get("anchor_timecode"):
        parts.append(f'timecode: {anchor_metadata["anchor_timecode"]}')
    return parts


def format_chunk_header(
    index: int,
    chunk: RetrievedChunk,
    source_map: dict[uuid.UUID, SourceInfo],
) -> str:
    source_info = source_map.get(chunk.source_id)
    if source_info is None:
        return f"[source:{index}]"

    parts = _format_anchor_parts(title=source_info.title, anchor_metadata=chunk.anchor_metadata)
    if not parts:
        return f"[source:{index}]"
    return f"[source:{index}] ({', '.join(parts)})"


def format_parent_header(
    index: int,
    chunk: RetrievedChunk,
    source_map: dict[uuid.UUID, SourceInfo],
) -> str:
    source_info = source_map.get(chunk.source_id)
    anchor_metadata = chunk.parent_anchor_metadata or {
        "anchor_page": None,
        "anchor_chapter": None,
        "anchor_section": None,
        "anchor_timecode": None,
    }
    parts = _format_anchor_parts(
        title=source_info.title if source_info is not None else None,
        anchor_metadata=anchor_metadata,
    )
    label = f"[parent:{index}]"
    if not parts:
        return label
    return f"{label} ({', '.join(parts)})"


def format_hierarchy_context(
    index: int,
    chunk: RetrievedChunk,
    source_map: dict[uuid.UUID, SourceInfo],
    *,
    include_parent: bool,
) -> str:
    child_context = f"{format_chunk_header(index, chunk, source_map)}\n{chunk.text_content}"
    if not include_parent or not chunk.parent_text_content:
        return child_context
    return "\n".join(
        [
            format_parent_header(index, chunk, source_map),
            chunk.parent_text_content,
            "",
            f"Matched excerpt: {format_chunk_header(index, chunk, source_map)}",
            chunk.text_content,
        ]
    )
