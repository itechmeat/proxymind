from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.persona.loader import PersonaContext
from app.persona.safety import SYSTEM_SAFETY_POLICY
from app.services.qdrant import RetrievedChunk

if TYPE_CHECKING:
    from app.services.citation import SourceInfo

NO_CONTEXT_REFUSAL = "I could not find an answer to that in the knowledge base."

CITATION_INSTRUCTIONS = """## Citation Instructions
When your answer is based on the knowledge context below,
cite sources using [source:N] where N is the source number.
- Place citations inline, immediately after the relevant statement.
- Do not generate URLs or links. Only use source numbers provided.
- Cite only the most relevant sources for knowledge-based facts.
- Do not cite inferences or small talk."""


def _format_chunk_header(
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


def build_chat_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    persona: PersonaContext,
    source_map: dict[uuid.UUID, SourceInfo] | None = None,
) -> list[dict[str, str]]:
    system_sections = [SYSTEM_SAFETY_POLICY]
    if persona.identity:
        system_sections.append(persona.identity)
    if persona.soul:
        system_sections.append(persona.soul)
    if persona.behavior:
        system_sections.append(persona.behavior)
    if chunks and source_map is not None:
        system_sections.append(CITATION_INSTRUCTIONS)

    user_sections: list[str] = []

    if chunks:
        context_lines = ["Knowledge context:"]
        for index, chunk in enumerate(chunks, start=1):
            if source_map is None:
                context_lines.append(
                    f"[Chunk {index}] source_id={chunk.source_id} score={chunk.score:.4f}"
                )
            else:
                context_lines.append(_format_chunk_header(index, chunk, source_map))
            context_lines.append(chunk.text_content)
        user_sections.append("\n".join(context_lines))

    user_sections.append(f"Question:\n{query}")
    return [
        {"role": "system", "content": "\n\n".join(system_sections)},
        {"role": "user", "content": "\n\n".join(user_sections)},
    ]
