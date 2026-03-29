from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CatalogItem, Source
from app.services.qdrant import RetrievedChunk

_CITATION_PATTERN = re.compile(r"\[source:(\d+)\]")


@dataclass(slots=True, frozen=True)
class SourceInfo:
    id: uuid.UUID
    title: str
    public_url: str | None
    source_type: str
    catalog_item_url: str | None = None
    catalog_item_name: str | None = None
    catalog_item_type: str | None = None
    catalog_item_active: bool = False


@dataclass(slots=True, frozen=True)
class Citation:
    index: int
    source_id: uuid.UUID
    source_title: str
    source_type: str
    url: str | None
    anchor: dict[str, int | str | None]
    text_citation: str
    purchase_url: str | None = None
    purchase_title: str | None = None
    catalog_item_type: str | None = None

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
            purchase_url=value.get("purchase_url"),
            purchase_title=value.get("purchase_title"),
            catalog_item_type=value.get("catalog_item_type"),
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
            "purchase_url": self.purchase_url,
            "purchase_title": self.purchase_title,
            "catalog_item_type": self.catalog_item_type,
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


def _is_catalog_item_active(
    *,
    is_active: bool | None,
    valid_from: datetime | None,
    valid_until: datetime | None,
    deleted_at: datetime | None,
) -> bool:
    if not is_active or deleted_at is not None:
        return False

    today = datetime.now(UTC).date()
    valid_from_date = valid_from.date() if valid_from is not None else None
    valid_until_date = valid_until.date() if valid_until is not None else None
    if valid_from_date is not None and valid_from_date > today:
        return False
    if valid_until_date is not None and valid_until_date < today:
        return False
    return True


async def load_source_map(
    session: AsyncSession,
    source_ids: list[uuid.UUID],
) -> dict[uuid.UUID, SourceInfo]:
    if not source_ids:
        return {}

    rows = await session.execute(
        select(
            Source.id,
            Source.title,
            Source.public_url,
            Source.source_type,
            CatalogItem.id.label("catalog_item_id"),
            CatalogItem.url.label("catalog_item_url"),
            CatalogItem.name.label("catalog_item_name"),
            CatalogItem.item_type.label("catalog_item_type"),
            CatalogItem.is_active.label("catalog_item_is_active"),
            CatalogItem.valid_from.label("catalog_item_valid_from"),
            CatalogItem.valid_until.label("catalog_item_valid_until"),
            CatalogItem.deleted_at.label("catalog_item_deleted_at"),
        )
        .outerjoin(CatalogItem, Source.catalog_item_id == CatalogItem.id)
        .where(
            Source.id.in_(source_ids),
            Source.deleted_at.is_(None),
        )
    )
    return {
        row.id: SourceInfo(
            id=row.id,
            title=row.title,
            public_url=row.public_url,
            source_type=row.source_type.value,
            catalog_item_url=row.catalog_item_url,
            catalog_item_name=row.catalog_item_name,
            catalog_item_type=(row.catalog_item_type.value if row.catalog_item_type else None),
            catalog_item_active=_is_catalog_item_active(
                is_active=row.catalog_item_is_active,
                valid_from=row.catalog_item_valid_from,
                valid_until=row.catalog_item_valid_until,
                deleted_at=row.catalog_item_deleted_at,
            ),
        )
        for row in rows
    }


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
                    purchase_url=(
                        source_info.catalog_item_url if source_info.catalog_item_active else None
                    ),
                    purchase_title=(
                        source_info.catalog_item_name if source_info.catalog_item_active else None
                    ),
                    catalog_item_type=(
                        source_info.catalog_item_type if source_info.catalog_item_active else None
                    ),
                )
            )
            if len(citations) >= max_citations:
                break

        return citations
