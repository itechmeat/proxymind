from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from app.persona.loader import PersonaContext
from app.persona.safety import SYSTEM_SAFETY_POLICY
from app.services.catalog import CatalogItemInfo
from app.services.conversation_memory import MemoryBlock
from app.services.promotions import Promotion, PromotionsService
from app.services.prompt import format_chunk_header
from app.services.qdrant import RetrievedChunk
from app.services.token_counter import estimate_tokens

if TYPE_CHECKING:
    from app.services.citation import SourceInfo


@dataclass(slots=True, frozen=True)
class PromptLayer:
    tag: str
    content: str
    token_estimate: int


@dataclass(slots=True, frozen=True)
class AssembledPrompt:
    messages: list[dict[str, str]]
    token_estimate: int
    included_promotions: list[Promotion]
    catalog_items_used: list[CatalogItemInfo]
    retrieval_chunks_used: int
    retrieval_chunks_total: int
    layer_token_counts: dict[str, int]


class ContextAssembler:
    def __init__(
        self,
        *,
        persona_context: PersonaContext,
        retrieval_context_budget: int,
        max_citations: int,
        min_retrieved_chunks: int,
        promotions_service: PromotionsService | None = None,
        active_promotions: list[Promotion] | None = None,
        catalog_items: list[CatalogItemInfo] | None = None,
        max_promotions_per_response: int = 1,
    ) -> None:
        self.persona_context = persona_context
        self.promotions_service = promotions_service
        self._active_promotions = list(active_promotions or [])
        self._catalog_items = list(catalog_items or [])
        self._retrieval_context_budget = retrieval_context_budget
        self._max_citations = max_citations
        self._min_retrieved_chunks = min_retrieved_chunks
        self._max_promotions_per_response = max_promotions_per_response
        self._logger = structlog.get_logger(__name__)

    def assemble(
        self,
        *,
        chunks: list[RetrievedChunk],
        query: str,
        source_map: dict[uuid.UUID, SourceInfo],
        memory_block: MemoryBlock | None = None,
    ) -> AssembledPrompt:
        included_promotions = self._resolve_promotions()
        selected_chunks = self._select_chunks(chunks, source_map)

        layers = [
            self._build_layer("system_safety", SYSTEM_SAFETY_POLICY),
            self._build_layer("identity", self.persona_context.identity),
            self._build_layer("soul", self.persona_context.soul),
            self._build_layer("behavior", self.persona_context.behavior),
        ]
        if included_promotions:
            layers.append(
                self._build_layer(
                    "promotions",
                    self._promotions_text(included_promotions),
                )
            )
        if self._catalog_items:
            layers.append(
                self._build_layer(
                    "available_products",
                    self._build_available_products_layer(self._catalog_items),
                )
            )
        if memory_block is not None and memory_block.summary_text:
            layers.append(
                self._build_layer(
                    "conversation_summary",
                    f"Earlier in this conversation:\n{memory_block.summary_text}",
                )
            )
        if selected_chunks:
            layers.append(
                self._build_layer(
                    "citation_instructions",
                    self._citation_instructions(),
                )
            )
        if self._catalog_items:
            layers.append(
                self._build_layer(
                    "product_instructions",
                    self._build_product_instructions_layer(),
                )
            )
        layers.append(self._build_layer("content_guidelines", self._content_guidelines()))

        layer_token_counts = {layer.tag: layer.token_estimate for layer in layers}
        if memory_block is not None and memory_block.total_tokens > 0:
            layer_token_counts.pop("conversation_summary", None)
            layer_token_counts["conversation_memory"] = memory_block.total_tokens
        system_content = "\n\n".join(layer.content for layer in layers)
        messages = [{"role": "system", "content": system_content}]

        if memory_block is not None and memory_block.messages:
            messages.extend(memory_block.messages)

        user_sections = [self._build_user_query(query)]
        if selected_chunks:
            knowledge_context = self._build_knowledge_context(selected_chunks, source_map)
            user_sections.insert(0, knowledge_context)
            layer_token_counts["knowledge_context"] = estimate_tokens(knowledge_context)
        layer_token_counts["user_query"] = estimate_tokens(user_sections[-1])
        user_content = "\n\n".join(user_sections)
        messages.append({"role": "user", "content": user_content})

        return AssembledPrompt(
            messages=messages,
            token_estimate=sum(layer_token_counts.values()),
            included_promotions=included_promotions,
            catalog_items_used=list(self._catalog_items),
            retrieval_chunks_used=len(selected_chunks),
            retrieval_chunks_total=len(chunks),
            layer_token_counts=layer_token_counts,
        )

    def _resolve_promotions(self) -> list[Promotion]:
        promotions = self._active_promotions
        if self.promotions_service is not None:
            promotions = self.promotions_service.get_active(
                max_promotions=self._max_promotions_per_response,
            )
        if len(promotions) > 1:
            self._logger.warning(
                "context_assembler.multiple_promotions_requested",
                promotions_count=len(promotions),
            )
        return promotions[:1]

    def _select_chunks(
        self,
        chunks: list[RetrievedChunk],
        source_map: dict[uuid.UUID, SourceInfo],
    ) -> list[RetrievedChunk]:
        selected_chunks: list[RetrievedChunk] = []
        used_tokens = 0

        for chunk in chunks:
            next_index = len(selected_chunks) + 1
            formatted_chunk = (
                f"{format_chunk_header(next_index, chunk, source_map)}\n{chunk.text_content}"
            )
            chunk_tokens = estimate_tokens(formatted_chunk)
            if used_tokens + chunk_tokens > self._retrieval_context_budget:
                if len(selected_chunks) < self._min_retrieved_chunks:
                    self._logger.warning(
                        "context_assembler.retrieval_budget_exceeded_for_min_chunks",
                        retrieval_context_budget=self._retrieval_context_budget,
                        min_retrieved_chunks=self._min_retrieved_chunks,
                    )
                    selected_chunks.append(chunk)
                    used_tokens += chunk_tokens
                    continue
                break
            selected_chunks.append(chunk)
            used_tokens += chunk_tokens

        return selected_chunks

    def _build_layer(self, tag: str, text: str) -> PromptLayer:
        content = self._wrap(tag, text)
        return PromptLayer(
            tag=tag,
            content=content,
            token_estimate=estimate_tokens(content),
        )

    @staticmethod
    def _wrap(tag: str, text: str) -> str:
        return f"<{tag}>\n{text}\n</{tag}>"

    def _promotions_text(self, promotions: list[Promotion]) -> str:
        promotion = promotions[0]
        lines = [
            "You have one active promotion below. Mention it ONLY when it is naturally",
            "relevant to the conversation topic. Do not force or shoehorn it.",
            "Never mention more than one promotion per response.",
            "If the promotion is not relevant to the current question, do not mention it at all.",
            "",
            f"Title: {promotion.title}",
            *([f"Context hint: {promotion.context}"] if promotion.context else []),
            f"Details: {promotion.body}",
        ]
        return "\n".join(lines)

    def _citation_instructions(self) -> str:
        return "\n".join(
            [
                "Retrieved knowledge chunks are labeled [1], [2], etc.",
                "When your response uses information from a chunk, cite it as [source:N]",
                "where N is the chunk number. Rules:",
                "- Cite only chunks you actually use.",
                "- Place citations inline, immediately after the relevant statement.",
                "- Never generate URLs - only use [source:N] markers.",
                f"- Maximum {self._max_citations} citations per response.",
            ]
        )

    def _build_available_products_layer(self, catalog_items: list[CatalogItemInfo]) -> str:
        lines = [
            "You may recommend only products from this list when it is naturally relevant.",
            "When you mention a product, append its marker exactly as [product:N].",
            "Do not generate your own product markers or URLs.",
            "",
        ]
        for index, item in enumerate(catalog_items, start=1):
            lines.append(
                f'[product:{index}] "{item.name}" ({item.item_type.value}) - SKU: {item.sku}'
            )
        return "\n".join(lines)

    @staticmethod
    def _build_product_instructions_layer() -> str:
        return "\n".join(
            [
                "If you recommend a product, place [product:N] immediately after mentioning it.",
                "Maximum one product recommendation per response.",
                "Recommend only products listed in available_products.",
                "Do not generate URLs or invent product metadata.",
                "Recommend products only when they are naturally appropriate to the user's request.",
                "Product mentions must feel like genuine suggestions, not advertisements.",
            ]
        )

    @staticmethod
    def _content_guidelines() -> str:
        return "\n".join(
            [
                "Your response may contain three types of content:",
                "- Facts supported by retrieved sources - always cite with [source:N].",
                "- Inferences you derive from your knowledge - present as reasoning, not fact.",
                "- A recommendation from your active promotion - weave naturally if relevant.",
                "Keep these types distinct. Do not present inferences as sourced facts.",
            ]
        )

    def _build_knowledge_context(
        self,
        chunks: list[RetrievedChunk],
        source_map: dict[uuid.UUID, SourceInfo],
    ) -> str:
        lines: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            lines.append(format_chunk_header(index, chunk, source_map))
            lines.append(chunk.text_content)
            if index < len(chunks):
                lines.append("")
        return self._wrap("knowledge_context", "\n".join(lines))

    def _build_user_query(self, query: str) -> str:
        return self._wrap("user_query", query)
