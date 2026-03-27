from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.db.models import CatalogItem
from app.db.models.enums import CatalogItemType
from app.services.catalog import CatalogService


def _make_item(
    *,
    sku: str,
    is_active: bool = True,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    deleted_at: datetime | None = None,
) -> CatalogItem:
    return CatalogItem(
        id=uuid.uuid7(),
        agent_id=uuid.uuid7(),
        sku=sku,
        name=f"Item {sku}",
        item_type=CatalogItemType.BOOK,
        url=f"https://example.com/{sku.lower()}",
        image_url=f"https://example.com/{sku.lower()}.png",
        is_active=is_active,
        valid_from=valid_from,
        valid_until=valid_until,
        deleted_at=deleted_at,
    )


def test_filter_active_excludes_inactive_expired_future_and_deleted_items() -> None:
    today = date(2026, 3, 27)
    active = _make_item(sku="ACTIVE")
    inactive = _make_item(sku="INACTIVE", is_active=False)
    expired = _make_item(sku="EXPIRED", valid_until=datetime(2026, 1, 1, tzinfo=UTC))
    future = _make_item(sku="FUTURE", valid_from=datetime(2026, 6, 1, tzinfo=UTC))
    deleted = _make_item(sku="DELETED", deleted_at=datetime(2026, 3, 1, tzinfo=UTC))

    result = CatalogService.filter_active(
        [active, inactive, expired, future, deleted],
        today=today,
    )

    assert [item.sku for item in result] == ["ACTIVE"]


def test_filter_active_treats_same_day_datetime_as_valid() -> None:
    item = _make_item(
        sku="SAME-DAY",
        valid_until=datetime(2026, 3, 27, 23, 59, 59, tzinfo=UTC),
    )

    result = CatalogService.filter_active([item], today=date(2026, 3, 27))

    assert [catalog_item.sku for catalog_item in result] == ["SAME-DAY"]


def test_build_sku_map_returns_lightweight_lookup() -> None:
    first = _make_item(sku="BOOK-001")
    second = _make_item(sku="EVENT-001")

    result = CatalogService.build_sku_map([first, second])

    assert list(result) == ["BOOK-001", "EVENT-001"]
    assert result["BOOK-001"].name == first.name
    assert result["EVENT-001"].item_type is CatalogItemType.BOOK
