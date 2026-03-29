from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.services.document_processing import ChunkData


DEFAULT_PARENT_CHILD_MIN_DOCUMENT_TOKENS = 1500
DEFAULT_PARENT_CHILD_MIN_FLAT_CHUNKS = 6
DEFAULT_PARENT_CHILD_PARENT_TARGET_TOKENS = 1200
DEFAULT_PARENT_CHILD_PARENT_MAX_TOKENS = 1800


@dataclass(slots=True, frozen=True)
class HierarchyDecision:
    qualifies: bool
    reason: str
    has_structure: bool
    total_tokens: int
    chunk_count: int


@dataclass(slots=True, frozen=True)
class ParentChunkData:
    parent_index: int
    text_content: str
    token_count: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None
    heading_path: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ChildChunkLink:
    chunk_index: int
    parent_index: int


@dataclass(slots=True, frozen=True)
class ChunkHierarchy:
    parents: list[ParentChunkData]
    children: list[ChildChunkLink]
    decision: HierarchyDecision


class ChunkHierarchyBuilder:
    def __init__(
        self,
        *,
        min_document_tokens: int,
        min_flat_chunks: int,
        parent_target_tokens: int,
        parent_max_tokens: int,
    ) -> None:
        self._min_document_tokens = min_document_tokens
        self._min_flat_chunks = min_flat_chunks
        self._parent_target_tokens = parent_target_tokens
        self._parent_max_tokens = parent_max_tokens

    @classmethod
    def from_settings(cls, settings: Settings) -> ChunkHierarchyBuilder:
        return cls(
            min_document_tokens=getattr(
                settings,
                "parent_child_min_document_tokens",
                DEFAULT_PARENT_CHILD_MIN_DOCUMENT_TOKENS,
            ),
            min_flat_chunks=getattr(
                settings,
                "parent_child_min_flat_chunks",
                DEFAULT_PARENT_CHILD_MIN_FLAT_CHUNKS,
            ),
            parent_target_tokens=getattr(
                settings,
                "parent_child_parent_target_tokens",
                DEFAULT_PARENT_CHILD_PARENT_TARGET_TOKENS,
            ),
            parent_max_tokens=getattr(
                settings,
                "parent_child_parent_max_tokens",
                DEFAULT_PARENT_CHILD_PARENT_MAX_TOKENS,
            ),
        )

    def qualify(self, chunks: list[ChunkData]) -> HierarchyDecision:
        total_tokens = sum(self._chunk_tokens(chunk) for chunk in chunks)
        chunk_count = len(chunks)
        has_structure = any(chunk.anchor_chapter or chunk.anchor_section for chunk in chunks)
        if total_tokens < self._min_document_tokens or chunk_count < self._min_flat_chunks:
            return HierarchyDecision(
                qualifies=False,
                reason="below_long_form_threshold",
                has_structure=has_structure,
                total_tokens=total_tokens,
                chunk_count=chunk_count,
            )
        if has_structure:
            return HierarchyDecision(
                qualifies=True,
                reason="long_form_structure_first",
                has_structure=has_structure,
                total_tokens=total_tokens,
                chunk_count=chunk_count,
            )
        return HierarchyDecision(
            qualifies=True,
            reason="long_form_fallback",
            has_structure=has_structure,
            total_tokens=total_tokens,
            chunk_count=chunk_count,
        )

    def build(self, chunks: list[ChunkData]) -> ChunkHierarchy:
        decision = self.qualify(chunks)
        if not chunks or not decision.qualifies:
            return ChunkHierarchy(parents=[], children=[], decision=decision)

        grouped_chunks = self._group_chunks(chunks, decision.has_structure)
        parents: list[ParentChunkData] = []
        children: list[ChildChunkLink] = []

        for parent_index, group in enumerate(grouped_chunks):
            parent = self._build_parent(parent_index, group)
            assert isinstance(parent.heading_path, tuple)
            parents.append(parent)
            children.extend(
                ChildChunkLink(chunk_index=chunk.chunk_index, parent_index=parent_index)
                for chunk in group
            )

        return ChunkHierarchy(parents=parents, children=children, decision=decision)

    def _group_chunks(
        self,
        chunks: list[ChunkData],
        has_structure: bool,
    ) -> list[list[ChunkData]]:
        if not has_structure:
            return self._split_bounded(chunks)

        structural_groups: list[list[ChunkData]] = []
        current_group: list[ChunkData] = []
        current_key: tuple[str | None, str | None] | None = None

        for chunk in chunks:
            group_key = (chunk.anchor_chapter, chunk.anchor_section)
            if current_group and group_key != current_key:
                structural_groups.extend(self._split_bounded(current_group))
                current_group = []
            current_group.append(chunk)
            current_key = group_key

        if current_group:
            structural_groups.extend(self._split_bounded(current_group))

        return structural_groups

    def _split_bounded(self, chunks: list[ChunkData]) -> list[list[ChunkData]]:
        groups: list[list[ChunkData]] = []
        current_group: list[ChunkData] = []
        current_tokens = 0

        for chunk in chunks:
            chunk_tokens = self._chunk_tokens(chunk)
            would_exceed = current_group and (current_tokens + chunk_tokens) > self._parent_max_tokens
            reached_target = current_group and current_tokens >= self._parent_target_tokens

            if would_exceed or reached_target:
                groups.append(current_group)
                current_group = []
                current_tokens = 0

            current_group.append(chunk)
            current_tokens += chunk_tokens

        if current_group:
            groups.append(current_group)

        return groups

    def _build_parent(self, parent_index: int, chunks: list[ChunkData]) -> ParentChunkData:
        anchor_page = self._first_non_null(chunks, "anchor_page")
        anchor_chapter = self._first_non_null(chunks, "anchor_chapter")
        anchor_section = self._first_non_null(chunks, "anchor_section")
        anchor_timecode = self._first_non_null(chunks, "anchor_timecode")
        heading_path = tuple(
            value
            for value in (anchor_chapter, anchor_section)
            if value is not None
        )
        return ParentChunkData(
            parent_index=parent_index,
            text_content="\n\n".join(chunk.text_content for chunk in chunks),
            token_count=sum(self._chunk_tokens(chunk) for chunk in chunks),
            anchor_page=anchor_page,
            anchor_chapter=anchor_chapter,
            anchor_section=anchor_section,
            anchor_timecode=anchor_timecode,
            heading_path=heading_path,
        )

    @staticmethod
    def _chunk_tokens(chunk: ChunkData) -> int:
        return max(1, chunk.token_count)

    @staticmethod
    def _first_non_null(chunks: list[ChunkData], field_name: str):
        for chunk in chunks:
            value = getattr(chunk, field_name)
            if value is not None:
                return value
        return None
