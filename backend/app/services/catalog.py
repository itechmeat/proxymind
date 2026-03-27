from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.catalog_schemas import CatalogItemCreate, CatalogItemUpdate
from app.db.models import CatalogItem
from app.db.models.enums import CatalogItemType


class CatalogItemNotFoundError(RuntimeError):
    pass


class CatalogItemConflictError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class CatalogItemInfo:
    id: uuid.UUID
    sku: str
    name: str
    item_type: CatalogItemType
    url: str | None
    image_url: str | None


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        payload: CatalogItemCreate,
        *,
        agent_id: uuid.UUID,
    ) -> CatalogItem:
        item = CatalogItem(
            id=uuid.uuid7(),
            agent_id=agent_id,
            sku=payload.sku,
            name=payload.name,
            description=payload.description,
            item_type=payload.item_type,
            url=str(payload.url) if payload.url else None,
            image_url=str(payload.image_url) if payload.image_url else None,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
        )
        self._session.add(item)
        return await self._commit_item(item)

    async def get_by_id(self, item_id: uuid.UUID, *, agent_id: uuid.UUID) -> CatalogItem:
        item = await self._session.scalar(
            select(CatalogItem)
            .where(
                CatalogItem.id == item_id,
                CatalogItem.agent_id == agent_id,
                CatalogItem.deleted_at.is_(None),
            )
            .options(selectinload(CatalogItem.sources))
        )
        if item is None:
            raise CatalogItemNotFoundError("Catalog item not found")
        return item

    async def list_items(
        self,
        *,
        agent_id: uuid.UUID,
        item_type: CatalogItemType | None,
        is_active: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[CatalogItem], int]:
        filters = [
            CatalogItem.agent_id == agent_id,
            CatalogItem.deleted_at.is_(None),
            CatalogItem.is_active.is_(is_active),
        ]
        if item_type is not None:
            filters.append(CatalogItem.item_type == item_type)

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(CatalogItem).where(*filters)
            )
            or 0
        )
        items = (
            await self._session.scalars(
                select(CatalogItem)
                .where(*filters)
                .options(selectinload(CatalogItem.sources))
                .order_by(CatalogItem.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return items, total

    async def update(
        self,
        item_id: uuid.UUID,
        payload: CatalogItemUpdate,
        *,
        agent_id: uuid.UUID,
    ) -> CatalogItem:
        item = await self.get_by_id(item_id, agent_id=agent_id)
        for field_name, value in payload.model_dump(exclude_unset=True).items():
            if field_name in {"url", "image_url"} and value is not None:
                setattr(item, field_name, str(value))
                continue
            setattr(item, field_name, value)
        return await self._commit_item(item)

    async def soft_delete(self, item_id: uuid.UUID, *, agent_id: uuid.UUID) -> CatalogItem:
        item = await self.get_by_id(item_id, agent_id=agent_id)
        item.is_active = False
        item.deleted_at = datetime.now(UTC)
        return await self._commit_item(item)

    async def get_active_items(
        self,
        *,
        agent_id: uuid.UUID,
        today: date | None = None,
    ) -> list[CatalogItem]:
        items = (
            await self._session.scalars(
                select(CatalogItem)
                .where(
                    CatalogItem.agent_id == agent_id,
                    CatalogItem.deleted_at.is_(None),
                    CatalogItem.is_active.is_(True),
                )
                .order_by(CatalogItem.created_at.desc())
            )
        ).all()
        return self.filter_active(items, today=today)

    @staticmethod
    def filter_active(
        items: list[CatalogItem],
        *,
        today: date | None = None,
    ) -> list[CatalogItem]:
        effective_today = today or datetime.now(UTC).date()
        filtered: list[CatalogItem] = []
        for item in items:
            if not item.is_active or item.deleted_at is not None:
                continue
            valid_from = CatalogService._to_date(item.valid_from)
            valid_until = CatalogService._to_date(item.valid_until)
            if valid_from is not None and valid_from > effective_today:
                continue
            if valid_until is not None and valid_until < effective_today:
                continue
            filtered.append(item)
        return filtered

    @staticmethod
    def build_sku_map(items: list[CatalogItem]) -> dict[str, CatalogItemInfo]:
        return {
            item.sku: CatalogItemInfo(
                id=item.id,
                sku=item.sku,
                name=item.name,
                item_type=item.item_type,
                url=item.url,
                image_url=item.image_url,
            )
            for item in items
        }

    @staticmethod
    def _to_date(value: datetime | None) -> date | None:
        if value is None:
            return None
        return value.date()

    async def _commit_item(self, item: CatalogItem) -> CatalogItem:
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            if self._is_sku_conflict(error):
                raise CatalogItemConflictError("Catalog item with this SKU already exists") from error
            raise

        await self._session.refresh(item)
        return item

    def _is_sku_conflict(self, error: IntegrityError) -> bool:
        original_error = getattr(error, "orig", None)
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name == "uq_catalog_items_agent_id_sku":
            return True

        message = str(original_error or error)
        return "uq_catalog_items_agent_id_sku" in message
