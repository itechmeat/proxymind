from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import CatalogItem, Source
from app.db.models.enums import CatalogItemType, SourceStatus, SourceType


async def _create_catalog_item(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    sku: str,
    agent_id: uuid.UUID = DEFAULT_AGENT_ID,
    name: str = "Catalog item",
    item_type: CatalogItemType = CatalogItemType.BOOK,
    is_active: bool = True,
    deleted_at: datetime | None = None,
) -> CatalogItem:
    async with session_factory() as session:
        item = CatalogItem(
            id=uuid.uuid7(),
            agent_id=agent_id,
            sku=sku,
            name=name,
            item_type=item_type,
            is_active=is_active,
            deleted_at=deleted_at,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def _create_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    catalog_item_id: uuid.UUID | None = None,
    deleted_at: datetime | None = None,
) -> Source:
    async with session_factory() as session:
        source = Source(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=SourceType.MARKDOWN,
            title=title,
            file_path=f"sources/{title}.md",
            status=SourceStatus.READY,
            catalog_item_id=catalog_item_id,
            deleted_at=deleted_at,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        return source


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_catalog_crud_endpoints_and_filters(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    created = await api_client.post(
        "/api/admin/catalog",
        json={
            "sku": "BOOK-001",
            "name": "AI in Practice",
            "item_type": "book",
            "url": "https://example.com/book",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["sku"] == "BOOK-001"
    assert body["is_active"] is True

    duplicate = await api_client.post(
        "/api/admin/catalog",
        json={
            "sku": "BOOK-001",
            "name": "Duplicate",
            "item_type": "book",
        },
    )
    assert duplicate.status_code == 409

    inactive = await _create_catalog_item(
        session_factory,
        sku="COURSE-001",
        name="Inactive course",
        item_type=CatalogItemType.COURSE,
        is_active=False,
    )
    await _create_catalog_item(
        session_factory,
        sku="DELETED-001",
        name="Deleted item",
        deleted_at=datetime(2026, 3, 27, tzinfo=UTC),
    )

    listed = await api_client.get("/api/admin/catalog")
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["total"] == 1
    assert [item["sku"] for item in listed_body["items"]] == ["BOOK-001"]
    assert listed_body["items"][0]["linked_sources_count"] == 0

    inactive_list = await api_client.get("/api/admin/catalog", params={"is_active": "false"})
    assert inactive_list.status_code == 200
    assert [item["sku"] for item in inactive_list.json()["items"]] == [inactive.sku]

    catalog_id = uuid.UUID(body["id"])
    kept_source = await _create_source(session_factory, title="kept", catalog_item_id=catalog_id)
    await _create_source(
        session_factory,
        title="deleted",
        catalog_item_id=catalog_id,
        deleted_at=datetime(2026, 3, 27, tzinfo=UTC),
    )

    detail = await api_client.get(f"/api/admin/catalog/{catalog_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["linked_sources_count"] == 1
    assert detail_body["linked_sources"] == [
        {
            "id": str(kept_source.id),
            "title": "kept",
            "source_type": "markdown",
            "status": "ready",
        }
    ]

    updated = await api_client.patch(
        f"/api/admin/catalog/{catalog_id}",
        json={"name": "AI in Practice 2", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "AI in Practice 2"
    assert updated.json()["is_active"] is False

    deleted = await api_client.delete(f"/api/admin/catalog/{catalog_id}")
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_patch_catalog_item_handles_conflict_and_explicit_null_clears(
    api_client,
) -> None:
    created = await api_client.post(
        "/api/admin/catalog",
        json={
            "sku": "BOOK-010",
            "name": "Filled item",
            "description": "Has description",
            "item_type": "book",
            "url": "https://example.com/book-010",
            "image_url": "https://example.com/book-010.png",
            "valid_from": "2026-03-01T00:00:00Z",
            "valid_until": "2026-04-01T00:00:00Z",
        },
    )
    assert created.status_code == 201
    created_id = created.json()["id"]

    other = await api_client.post(
        "/api/admin/catalog",
        json={
            "sku": "BOOK-011",
            "name": "Other item",
            "item_type": "book",
        },
    )
    assert other.status_code == 201

    cleared = await api_client.patch(
        f"/api/admin/catalog/{created_id}",
        json={
            "description": None,
            "url": None,
            "image_url": None,
            "valid_from": None,
            "valid_until": None,
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None
    assert cleared.json()["url"] is None
    assert cleared.json()["image_url"] is None
    assert cleared.json()["valid_from"] is None
    assert cleared.json()["valid_until"] is None

    conflict = await api_client.patch(
        f"/api/admin/catalog/{created_id}",
        json={"sku": "BOOK-011"},
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_catalog_allows_same_sku_for_different_agents(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await _create_catalog_item(
        session_factory,
        sku="SHARED-001",
        agent_id=DEFAULT_AGENT_ID,
    )
    second = await _create_catalog_item(
        session_factory,
        sku="SHARED-001",
        agent_id=uuid.uuid7(),
        name="Other tenant item",
    )

    assert first.sku == second.sku
    assert first.agent_id != second.agent_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_patch_source_links_and_unlinks_catalog_item(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    item = await _create_catalog_item(session_factory, sku="EVENT-001", name="Conference")
    source = await _create_source(session_factory, title="promo")

    link_response = await api_client.patch(
        f"/api/admin/sources/{source.id}",
        json={"catalog_item_id": str(item.id)},
    )

    assert link_response.status_code == 200
    assert link_response.json()["catalog_item_id"] == str(item.id)

    noop_response = await api_client.patch(f"/api/admin/sources/{source.id}", json={})
    assert noop_response.status_code == 200
    assert noop_response.json()["catalog_item_id"] == str(item.id)

    unlink_response = await api_client.patch(
        f"/api/admin/sources/{source.id}",
        json={"catalog_item_id": None},
    )
    assert unlink_response.status_code == 200
    assert unlink_response.json()["catalog_item_id"] is None

    missing_item_response = await api_client.patch(
        f"/api/admin/sources/{source.id}",
        json={"catalog_item_id": str(uuid.uuid7())},
    )
    assert missing_item_response.status_code == 404
    assert missing_item_response.json()["detail"] == "Catalog item not found"
