from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.services.qdrant import RetrievedChunk

if TYPE_CHECKING:
    from app.services.citation import SourceInfo

NO_CONTEXT_REFUSAL = "I could not find an answer to that in the knowledge base."

def format_chunk_header(
    index: int,
    chunk: RetrievedChunk,
    source_map: dict[uuid.UUID, SourceInfo],
) -> str:
    source_info = source_map.get(chunk.source_id)
    if source_info is None:
        return f"[source:{index}]"

    parts = [f'title: "{source_info.title}"']
    if chunk.anchor_metadata.get("anchor_chapter"):
        parts.append(f'chapter: "{chunk.anchor_metadata["anchor_chapter"]}"')
    # Prompt context keeps both fields when available so the model gets the most specific locator.
    if chunk.anchor_metadata.get("anchor_section"):
        parts.append(f'section: "{chunk.anchor_metadata["anchor_section"]}"')
    if chunk.anchor_metadata.get("anchor_page") is not None:
        parts.append(f'page: {chunk.anchor_metadata["anchor_page"]}')
    if chunk.anchor_metadata.get("anchor_timecode"):
        parts.append(f'timecode: {chunk.anchor_metadata["anchor_timecode"]}')
    return f"[source:{index}] ({', '.join(parts)})"
