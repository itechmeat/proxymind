from __future__ import annotations

from app.persona.loader import PersonaContext
from app.persona.safety import SYSTEM_SAFETY_POLICY
from app.services.qdrant import RetrievedChunk

NO_CONTEXT_REFUSAL = "I could not find an answer to that in the knowledge base."


def build_chat_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    persona: PersonaContext,
) -> list[dict[str, str]]:
    system_sections = [SYSTEM_SAFETY_POLICY]
    if persona.identity:
        system_sections.append(persona.identity)
    if persona.soul:
        system_sections.append(persona.soul)
    if persona.behavior:
        system_sections.append(persona.behavior)

    user_sections: list[str] = []

    if chunks:
        context_lines = ["Knowledge context:"]
        for index, chunk in enumerate(chunks, start=1):
            context_lines.append(
                f"[Chunk {index}] source_id={chunk.source_id} score={chunk.score:.4f}"
            )
            context_lines.append(chunk.text_content)
        user_sections.append("\n".join(context_lines))

    user_sections.append(f"Question:\n{query}")
    return [
        {"role": "system", "content": "\n\n".join(system_sections)},
        {"role": "user", "content": "\n\n".join(user_sections)},
    ]
