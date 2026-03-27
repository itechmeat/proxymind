# S6-01: Commerce Backend — Catalog + Recommendations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add catalog CRUD, citation enrichment with purchase links, and product recommendation mechanism via `[product:N]` markers integrated with PROMOTIONS.md.

**Architecture:** Two independent delivery mechanisms: (1) automatic citation enrichment when cited source has a linked catalog item, (2) optional `[product:N]` markers for product recommendations driven by PROMOTIONS.md + catalog SKU matching. New `ProductRecommendationService` mirrors `CitationService` pattern. `ContextAssembler` gains `available_products` and `product_instructions` prompt layers.

**Tech Stack:** Python 3.14+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic 2.x, pytest, structlog

**Spec:** `docs/superpowers/specs/2026-03-27-s6-01-commerce-backend-design.md`

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `backend/app/services/catalog.py` | Catalog CRUD service |
| `backend/app/services/product_recommendation.py` | `[product:N]` marker parsing + enrichment |
| `backend/app/api/catalog_schemas.py` | Pydantic schemas for catalog API |
| `backend/migrations/versions/011_add_catalog_sku_and_fk_ondelete.py` | Migration: add `sku`, fix FK |
| `backend/tests/unit/test_catalog_service.py` | Catalog CRUD unit tests |
| `backend/tests/unit/test_product_recommendation.py` | Product recommendation unit tests |

### Modified files
| File | What changes |
|------|-------------|
| `backend/app/db/models/core.py` | Add `sku` field to `CatalogItem` |
| `backend/app/db/models/knowledge.py` | Add `ondelete="SET NULL"` to FK |
| `backend/app/services/citation.py` | Extend `SourceInfo`, `Citation` with purchase fields |
| `backend/app/services/promotions.py` | Extend `Promotion` with `catalog_item_sku`, parse new metadata |
| `backend/app/services/context_assembler.py` | Add `available_products` + `product_instructions` layers |
| `backend/app/services/chat.py` | Extend `_load_source_map()`, wire product recommendations |
| `backend/app/api/admin.py` | Add catalog CRUD + source PATCH endpoints |
| `backend/app/api/chat.py` | Add `ChatStreamProducts` SSE event |
| `backend/app/api/source_schemas.py` | Add `catalog_item_id` to `SourceListItem` |
| `backend/app/services/__init__.py` | Register new services |
| `backend/tests/unit/test_citation_service.py` | Add purchase enrichment tests |
| `backend/tests/unit/test_promotions.py` | Add catalog_item_sku parsing tests |
| `backend/tests/unit/test_context_assembler.py` | Add available_products layer tests |
| `config/PROMOTIONS.md` | Add `Catalog item:` metadata to existing entries |

---

## Task 1: Migration + Model Changes

**Files:**
- Modify: `backend/app/db/models/core.py:33-54`
- Modify: `backend/app/db/models/knowledge.py:56-59`
- Create: `backend/migrations/versions/011_add_catalog_sku_and_fk_ondelete.py`

- [ ] **Step 1: Add `sku` field to CatalogItem model**

In `backend/app/db/models/core.py`, add after the `name` field (line 35):

```python
sku: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
```

- [ ] **Step 2: Fix FK ondelete on Source model**

In `backend/app/db/models/knowledge.py`, change line 57 from:

```python
ForeignKey("catalog_items.id"),
```

to:

```python
ForeignKey("catalog_items.id", ondelete="SET NULL"),
```

- [ ] **Step 3: Create Alembic migration**

Create `backend/migrations/versions/011_add_catalog_sku_and_fk_ondelete.py`:

```python
"""add_catalog_sku_and_fk_ondelete

Revision ID: 011
Revises: 010
Create Date: 2026-03-27 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add sku column as nullable first (safe for existing rows)
    op.add_column(
        "catalog_items",
        sa.Column("sku", sa.String(64), nullable=True),
    )
    # Step 2: Backfill existing rows with unique SKUs derived from their full UUID
    op.execute(
        "UPDATE catalog_items SET sku = 'LEGACY-' || id::text WHERE sku IS NULL"
    )
    # Step 3: Now make column NOT NULL (all rows have values)
    op.alter_column("catalog_items", "sku", nullable=False)
    # Step 4: Create unique index (safe — all values are unique)
    op.create_index("ix_catalog_items_sku", "catalog_items", ["sku"], unique=True)

    # Fix FK ondelete: drop old FK, recreate with SET NULL
    op.drop_constraint(
        "sources_catalog_item_id_fkey", "sources", type_="foreignkey"
    )
    op.create_foreign_key(
        "sources_catalog_item_id_fkey",
        "sources",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


    # Step 5: Add products JSONB column to messages table
    op.add_column(
        "messages",
        sa.Column("products", sa.dialects.postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "products")
    op.drop_constraint(
        "sources_catalog_item_id_fkey", "sources", type_="foreignkey"
    )
    op.create_foreign_key(
        "sources_catalog_item_id_fkey",
        "sources",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
    )
    op.drop_index("ix_catalog_items_sku", "catalog_items")
    op.drop_column("catalog_items", "sku")
```

- [ ] **Step 4: Run migration in Docker**

```bash
docker compose exec api alembic upgrade head
```

Expected: Migration applies successfully, `catalog_items` table has `sku` column with unique index.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/core.py backend/app/db/models/knowledge.py backend/migrations/versions/011_add_catalog_sku_and_fk_ondelete.py
git commit -m "feat(catalog): add sku field and fix FK ondelete to SET NULL"
```

---

## Task 2: Catalog Pydantic Schemas

**Files:**
- Create: `backend/app/api/catalog_schemas.py`
- Modify: `backend/app/api/source_schemas.py:11-22`

- [ ] **Step 1: Create catalog schemas**

Create `backend/app/api/catalog_schemas.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import CatalogItemType, SourceStatus, SourceType


class CatalogItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    item_type: CatalogItemType
    url: str | None = Field(default=None, max_length=2048)
    image_url: str | None = Field(default=None, max_length=2048)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class CatalogItemUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    item_type: CatalogItemType | None = None
    url: str | None = None
    image_url: str | None = None
    is_active: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class LinkedSourceInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: SourceStatus


class CatalogItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    item_type: CatalogItemType
    url: str | None
    image_url: str | None
    is_active: bool
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime
    updated_at: datetime
    linked_sources_count: int = 0


class CatalogItemDetail(CatalogItemResponse):
    linked_sources: list[LinkedSourceInfo] = []


class CatalogItemListResponse(BaseModel):
    items: list[CatalogItemResponse]
    total: int


_UNSET = object()


class SourceUpdateRequest(BaseModel):
    """PATCH body for source updates. Uses exclude_unset pattern:
    - field absent from body → not changed
    - field explicitly null → unlink (set to None)
    - field with UUID → link to that catalog item
    """
    catalog_item_id: uuid.UUID | None = None
```

- [ ] **Step 2: Add `catalog_item_id` to SourceListItem**

In `backend/app/api/source_schemas.py`, add after `language` field:

```python
catalog_item_id: uuid.UUID | None
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/catalog_schemas.py backend/app/api/source_schemas.py
git commit -m "feat(catalog): add Pydantic schemas for catalog CRUD and source update"
```

---

## Task 3: CatalogService — CRUD

**Files:**
- Create: `backend/tests/unit/test_catalog_service.py`
- Create: `backend/app/services/catalog.py`
- Modify: `backend/app/services/__init__.py`

- [ ] **Step 1: Write failing tests for CatalogService**

Create `backend/tests/unit/test_catalog_service.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import CatalogItemType
from app.services.catalog import CatalogService


def _mock_catalog_item(
    *,
    sku: str = "TEST-SKU-001",
    name: str = "Test Product",
    item_type: CatalogItemType = CatalogItemType.BOOK,
    is_active: bool = True,
    url: str | None = "https://store.example.com/test",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> MagicMock:
    """Note: valid_from/valid_until use datetime to match the DB model."""
    item = MagicMock()
    item.id = uuid.uuid4()
    item.sku = sku
    item.name = name
    item.item_type = item_type
    item.is_active = is_active
    item.url = url
    item.valid_from = valid_from
    item.valid_until = valid_until
    item.description = None
    item.image_url = None
    item.deleted_at = None
    item.created_at = datetime(2026, 1, 1)
    item.updated_at = datetime(2026, 1, 1)
    item.sources = []
    return item


class TestCatalogServiceGetActiveItems:
    def test_filters_inactive_items(self) -> None:
        active = _mock_catalog_item(is_active=True)
        inactive = _mock_catalog_item(is_active=False)
        items = [active, inactive]
        result = CatalogService.filter_active(items, today=date(2026, 3, 27))
        assert len(result) == 1
        assert result[0].sku == active.sku

    def test_filters_expired_items(self) -> None:
        expired = _mock_catalog_item(
            valid_until=datetime(2026, 1, 1),
        )
        current = _mock_catalog_item(
            valid_until=datetime(2026, 12, 31),
        )
        items = [expired, current]
        result = CatalogService.filter_active(items, today=date(2026, 3, 27))
        assert len(result) == 1

    def test_filters_not_yet_valid_items(self) -> None:
        future = _mock_catalog_item(valid_from=datetime(2026, 6, 1))
        items = [future]
        result = CatalogService.filter_active(items, today=date(2026, 3, 27))
        assert len(result) == 0

    def test_items_without_dates_always_active(self) -> None:
        no_dates = _mock_catalog_item(valid_from=None, valid_until=None)
        items = [no_dates]
        result = CatalogService.filter_active(items, today=date(2026, 3, 27))
        assert len(result) == 1


class TestCatalogServiceBuildSkuMap:
    def test_builds_sku_to_info_mapping(self) -> None:
        item = _mock_catalog_item(sku="BOOK-001", name="Test Book")
        result = CatalogService.build_sku_map([item])
        assert "BOOK-001" in result
        assert result["BOOK-001"].name == "Test Book"

    def test_empty_list_returns_empty_map(self) -> None:
        result = CatalogService.build_sku_map([])
        assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_catalog_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.catalog'`

- [ ] **Step 3: Implement CatalogService**

Create `backend/app/services/catalog.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.core import CatalogItem
from app.db.models.enums import CatalogItemType
from app.db.models.knowledge import Source

logger = structlog.get_logger()


@dataclass(slots=True, frozen=True)
class CatalogItemInfo:
    """Lightweight catalog item data for prompt assembly and product recommendation."""

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
        *,
        sku: str,
        name: str,
        item_type: CatalogItemType,
        description: str | None = None,
        url: str | None = None,
        image_url: str | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        owner_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> CatalogItem:
        item = CatalogItem(
            sku=sku,
            name=name,
            item_type=item_type,
            description=description,
            url=url,
            image_url=image_url,
            valid_from=valid_from,
            valid_until=valid_until,
            owner_id=owner_id,
            agent_id=agent_id,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> CatalogItem | None:
        result = await self._session.execute(
            select(CatalogItem)
            .options(selectinload(CatalogItem.sources))
            .where(
                CatalogItem.id == item_id,
                CatalogItem.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_items(
        self,
        *,
        agent_id: uuid.UUID | None = None,
        item_type: CatalogItemType | None = None,
        is_active: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CatalogItem], int]:
        query = select(CatalogItem).where(CatalogItem.deleted_at.is_(None))
        count_query = select(func.count(CatalogItem.id)).where(
            CatalogItem.deleted_at.is_(None)
        )

        if agent_id is not None:
            query = query.where(CatalogItem.agent_id == agent_id)
            count_query = count_query.where(CatalogItem.agent_id == agent_id)
        if item_type is not None:
            query = query.where(CatalogItem.item_type == item_type)
            count_query = count_query.where(CatalogItem.item_type == item_type)
        if is_active:
            query = query.where(CatalogItem.is_active.is_(True))
            count_query = count_query.where(CatalogItem.is_active.is_(True))

        total = (await self._session.execute(count_query)).scalar_one()
        items = (
            await self._session.execute(
                query.order_by(CatalogItem.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()

        return list(items), total

    async def update(
        self,
        item: CatalogItem,
        **fields: object,
    ) -> CatalogItem:
        for key, value in fields.items():
            if value is not None:
                setattr(item, key, value)
        item.updated_at = datetime.now()  # noqa: DTZ005
        await self._session.flush()
        return item

    async def soft_delete(self, item: CatalogItem) -> CatalogItem:
        item.deleted_at = datetime.now()  # noqa: DTZ005
        item.is_active = False
        await self._session.flush()
        return item

    async def get_active_items(
        self,
        *,
        agent_id: uuid.UUID | None = None,
        today: date | None = None,
    ) -> list[CatalogItem]:
        """Load all active, non-expired catalog items for prompt assembly.
        Uses date (not datetime) for filtering — _to_date() handles conversion."""
        today = today or date.today()
        query = select(CatalogItem).where(
            CatalogItem.deleted_at.is_(None),
            CatalogItem.is_active.is_(True),
        )
        if agent_id is not None:
            query = query.where(CatalogItem.agent_id == agent_id)

        items = (await self._session.execute(query)).scalars().all()
        return self.filter_active(list(items), today=today)

    @staticmethod
    def _to_date(value: date | datetime | None) -> date | None:
        """Safely convert datetime to date for comparison."""
        if value is None:
            return None
        return value.date() if isinstance(value, datetime) else value

    @staticmethod
    def filter_active(
        items: list[CatalogItem],
        *,
        today: date,
    ) -> list[CatalogItem]:
        """Filter items by validity dates. Handles both date and datetime model fields."""
        result = []
        for item in items:
            if not item.is_active:
                continue
            valid_from = CatalogService._to_date(item.valid_from)
            valid_until = CatalogService._to_date(item.valid_until)
            if valid_from and valid_from > today:
                continue
            if valid_until and valid_until < today:
                continue
            result.append(item)
        return result

    @staticmethod
    def build_sku_map(items: list[CatalogItem]) -> dict[str, CatalogItemInfo]:
        """Build SKU -> CatalogItemInfo mapping for prompt assembly."""
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
```

- [ ] **Step 4: Register service in `__init__.py`**

Add to `backend/app/services/__init__.py` exports dict:

```python
"CatalogItemInfo": ("app.services.catalog", "CatalogItemInfo"),
"CatalogService": ("app.services.catalog", "CatalogService"),
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_catalog_service.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/catalog.py backend/app/services/__init__.py backend/tests/unit/test_catalog_service.py
git commit -m "feat(catalog): add CatalogService with CRUD, filtering, and SKU mapping"
```

---

## Task 4: Catalog API Endpoints

**Files:**
- Modify: `backend/app/api/admin.py`
- Test: via curl / httpie after Docker rebuild

- [ ] **Step 1: Add dependency provider for CatalogService**

Check how other services are injected in `admin.py` (e.g., `get_snapshot_service`). Add a similar provider. In the file where FastAPI dependencies are defined (check `backend/app/api/dependencies.py` or inline in admin.py), add:

```python
async def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogService:
    return CatalogService(session)
```

- [ ] **Step 2: Add catalog imports to admin.py**

At the top of `backend/app/api/admin.py`, add:

```python
from app.api.catalog_schemas import (
    CatalogItemCreate,
    CatalogItemDetail,
    CatalogItemListResponse,
    CatalogItemResponse,
    CatalogItemUpdate,
    LinkedSourceInfo,
    SourceUpdateRequest,
)
from app.services.catalog import CatalogService
```

- [ ] **Step 3: Add catalog list endpoint**

```python
@router.get("/catalog", response_model=CatalogItemListResponse)
async def list_catalog_items(
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    agent_id: uuid.UUID = Query(default=DEFAULT_AGENT_ID),
    item_type: CatalogItemType | None = Query(default=None),
    is_active: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CatalogItemListResponse:
    items, total = await catalog_service.list_items(
        agent_id=agent_id,
        item_type=item_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return CatalogItemListResponse(
        items=[
            CatalogItemResponse.model_validate(item, from_attributes=True)
            for item in items
        ],
        total=total,
    )
```

Note: `linked_sources_count` needs to be computed. If the list query doesn't load sources, set it to 0 in the list view (detail view provides the full list). Alternatively, add a subquery count — adapt based on existing patterns in admin.py.

- [ ] **Step 4: Add catalog detail endpoint**

```python
@router.get("/catalog/{item_id}", response_model=CatalogItemDetail)
async def get_catalog_item(
    item_id: uuid.UUID,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> CatalogItemDetail:
    item = await catalog_service.get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    active_sources = [s for s in item.sources if s.deleted_at is None]
    return CatalogItemDetail(
        **CatalogItemResponse.model_validate(item, from_attributes=True).model_dump(),
        linked_sources_count=len(active_sources),
        linked_sources=[
            LinkedSourceInfo.model_validate(s, from_attributes=True)
            for s in active_sources
        ],
    )
```

- [ ] **Step 5: Add catalog create endpoint**

```python
@router.post("/catalog", response_model=CatalogItemResponse, status_code=201)
async def create_catalog_item(
    payload: CatalogItemCreate,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    agent_id: uuid.UUID = Query(default=DEFAULT_AGENT_ID),
) -> CatalogItemResponse:
    try:
        item = await catalog_service.create(
            sku=payload.sku,
            name=payload.name,
            item_type=payload.item_type,
            description=payload.description,
            url=payload.url,
            image_url=payload.image_url,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
            agent_id=agent_id,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Catalog item with SKU '{payload.sku}' already exists",
        )
    return CatalogItemResponse.model_validate(item, from_attributes=True)
```

Add `from sqlalchemy.exc import IntegrityError` to imports.

- [ ] **Step 6: Add catalog update endpoint**

```python
@router.patch("/catalog/{item_id}", response_model=CatalogItemResponse)
async def update_catalog_item(
    item_id: uuid.UUID,
    payload: CatalogItemUpdate,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> CatalogItemResponse:
    item = await catalog_service.get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return CatalogItemResponse.model_validate(item, from_attributes=True)
    try:
        item = await catalog_service.update(item, **fields)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Catalog item with SKU '{payload.sku}' already exists",
        )
    return CatalogItemResponse.model_validate(item, from_attributes=True)
```

- [ ] **Step 7: Add catalog delete endpoint**

```python
@router.delete("/catalog/{item_id}", response_model=CatalogItemResponse)
async def delete_catalog_item(
    item_id: uuid.UUID,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> CatalogItemResponse:
    item = await catalog_service.get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    item = await catalog_service.soft_delete(item)
    return CatalogItemResponse.model_validate(item, from_attributes=True)
```

- [ ] **Step 8: Add source PATCH endpoint for re-linking**

```python
@router.patch("/sources/{source_id}", response_model=SourceListItem)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SourceListItem:
    result = await session.execute(
        select(Source).where(
            Source.id == source_id,
            Source.deleted_at.is_(None),
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    # Use exclude_unset to distinguish "field not sent" from "explicitly null"
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return SourceListItem.model_validate(source, from_attributes=True)

    if "catalog_item_id" in fields:
        new_id = fields["catalog_item_id"]
        if new_id is not None:
            # Verify catalog item exists
            cat_result = await session.execute(
                select(CatalogItem.id).where(
                    CatalogItem.id == new_id,
                    CatalogItem.deleted_at.is_(None),
                )
            )
            if cat_result.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Catalog item not found")
        source.catalog_item_id = new_id

    await session.flush()
    return SourceListItem.model_validate(source, from_attributes=True)
```

- [ ] **Step 9: Rebuild and test endpoints manually**

```bash
docker compose up --build -d
# Create catalog item
curl -s -X POST http://localhost:8000/api/admin/catalog \
  -H "Content-Type: application/json" \
  -d '{"sku":"TEST-001","name":"Test Book","item_type":"book","url":"https://store.example.com"}' | python -m json.tool
# List catalog items
curl -s http://localhost:8000/api/admin/catalog | python -m json.tool
```

Expected: 201 Created with catalog item data; GET returns list with the item.

- [ ] **Step 10: Commit**

```bash
git add backend/app/api/admin.py backend/app/api/catalog_schemas.py
git commit -m "feat(catalog): add CRUD API endpoints and source PATCH for re-linking"
```

---

## Task 5: Extend PromotionsService with catalog_item_sku

**Files:**
- Modify: `backend/tests/unit/test_promotions.py`
- Modify: `backend/app/services/promotions.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_promotions.py`:

```python
PROMO_WITH_CATALOG = """\
## Test Product

- **Priority:** high
- **Valid from:** 2026-01-01
- **Valid to:** 2026-12-31
- **Catalog item:** BOOK-001
- **Context:** When discussing books.

Check out this amazing book.
"""

PROMO_WITHOUT_CATALOG = """\
## Generic Promo

- **Priority:** medium
- **Valid from:** 2026-01-01
- **Valid to:** 2026-12-31
- **Context:** Always.

Some promotion text.
"""


class TestCatalogItemSkuParsing:
    def test_parses_catalog_item_sku(self) -> None:
        service = PromotionsService(promotions_text=PROMO_WITH_CATALOG)
        promos = service.parse()
        assert len(promos) == 1
        assert promos[0].catalog_item_sku == "BOOK-001"

    def test_missing_catalog_item_returns_none(self) -> None:
        service = PromotionsService(promotions_text=PROMO_WITHOUT_CATALOG)
        promos = service.parse()
        assert len(promos) == 1
        assert promos[0].catalog_item_sku is None

    def test_catalog_item_sku_stripped(self) -> None:
        text = PROMO_WITH_CATALOG.replace("BOOK-001", "  BOOK-002  ")
        service = PromotionsService(promotions_text=text)
        promos = service.parse()
        assert promos[0].catalog_item_sku == "BOOK-002"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_promotions.py::TestCatalogItemSkuParsing -v
```

Expected: `AttributeError: 'Promotion' object has no attribute 'catalog_item_sku'`

- [ ] **Step 3: Extend Promotion dataclass**

In `backend/app/services/promotions.py`, add field to `Promotion` (after `body`):

```python
catalog_item_sku: str | None
```

- [ ] **Step 4: Update parse() to extract catalog_item_sku**

In the `parse()` method, where metadata fields are extracted from `_META_LINE_RE` matches, add handling for the `"catalog item"` key (case-insensitive, consistent with existing key matching). After extracting other metadata fields, set:

```python
catalog_item_sku = meta.get("catalog item")
if catalog_item_sku:
    catalog_item_sku = catalog_item_sku.strip()
```

And pass `catalog_item_sku=catalog_item_sku or None` to the `Promotion()` constructor.

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_promotions.py -v
```

Expected: All tests PASS (existing + new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/promotions.py backend/tests/unit/test_promotions.py
git commit -m "feat(promotions): parse optional Catalog item SKU from PROMOTIONS.md"
```

---

## Task 6: ProductRecommendationService

**Files:**
- Create: `backend/tests/unit/test_product_recommendation.py`
- Create: `backend/app/services/product_recommendation.py`
- Modify: `backend/app/services/__init__.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_product_recommendation.py`:

```python
from __future__ import annotations

import uuid

import pytest

from app.db.models.enums import CatalogItemType
from app.services.catalog import CatalogItemInfo
from app.services.product_recommendation import (
    ProductRecommendation,
    ProductRecommendationService,
)


def _item(
    *,
    sku: str = "BOOK-001",
    name: str = "Test Book",
    item_type: CatalogItemType = CatalogItemType.BOOK,
    url: str | None = "https://store.example.com/book",
) -> CatalogItemInfo:
    return CatalogItemInfo(
        id=uuid.uuid4(),
        sku=sku,
        name=name,
        item_type=item_type,
        url=url,
        image_url=None,
    )


class TestProductRecommendationExtract:
    def test_extracts_single_marker(self) -> None:
        items = [_item(sku="BOOK-001", name="My Book")]
        text = "Check out My Book [product:1] for more details."
        result = ProductRecommendationService.extract(text, items)
        assert len(result) == 1
        assert result[0].sku == "BOOK-001"
        assert result[0].name == "My Book"
        assert result[0].index == 1

    def test_limits_to_one_recommendation(self) -> None:
        items = [
            _item(sku="BOOK-001", name="Book One"),
            _item(sku="EVENT-001", name="Event One"),
        ]
        text = "Read Book One [product:1] and attend Event One [product:2]."
        result = ProductRecommendationService.extract(text, items)
        assert len(result) == 1
        assert result[0].sku == "BOOK-001"

    def test_ignores_invalid_index_zero(self) -> None:
        items = [_item()]
        text = "Some text [product:0] here."
        result = ProductRecommendationService.extract(text, items)
        assert len(result) == 0

    def test_ignores_out_of_range_index(self) -> None:
        items = [_item()]
        text = "Some text [product:5] here."
        result = ProductRecommendationService.extract(text, items)
        assert len(result) == 0

    def test_no_markers_returns_empty(self) -> None:
        items = [_item()]
        text = "Just a regular response with no recommendations."
        result = ProductRecommendationService.extract(text, items)
        assert len(result) == 0

    def test_empty_catalog_returns_empty(self) -> None:
        text = "Some text [product:1] here."
        result = ProductRecommendationService.extract(text, [])
        assert len(result) == 0

    def test_deduplicates_by_catalog_item_id(self) -> None:
        item = _item(sku="BOOK-001")
        items = [item]
        text = "Read this [product:1] and again [product:1]."
        result = ProductRecommendationService.extract(text, items)
        assert len(result) == 1


class TestProductRecommendationStripMarkers:
    def test_strips_product_markers(self) -> None:
        text = "Check out My Book [product:1] for details."
        result = ProductRecommendationService.strip_markers(text)
        assert result == "Check out My Book  for details."

    def test_strips_multiple_markers(self) -> None:
        text = "Book [product:1] and event [product:2]."
        result = ProductRecommendationService.strip_markers(text)
        assert result == "Book  and event ."

    def test_no_markers_unchanged(self) -> None:
        text = "No markers here."
        result = ProductRecommendationService.strip_markers(text)
        assert result == "No markers here."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_product_recommendation.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.product_recommendation'`

- [ ] **Step 3: Implement ProductRecommendationService**

Create `backend/app/services/product_recommendation.py`:

```python
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.db.models.enums import CatalogItemType
from app.services.catalog import CatalogItemInfo

_PRODUCT_PATTERN = re.compile(r"\[product:(\d+)\]")


@dataclass(slots=True, frozen=True)
class ProductRecommendation:
    index: int
    catalog_item_id: uuid.UUID
    name: str
    sku: str
    item_type: CatalogItemType
    url: str | None
    image_url: str | None
    text_recommendation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "catalog_item_id": str(self.catalog_item_id),
            "name": self.name,
            "sku": self.sku,
            "item_type": self.item_type.value,
            "url": self.url,
            "image_url": self.image_url,
            "text_recommendation": self.text_recommendation,
        }


def _format_recommendation(item: CatalogItemInfo) -> str:
    return f"{item.name} ({item.item_type.value})"


class ProductRecommendationService:
    @staticmethod
    def extract(
        content: str,
        catalog_items: list[CatalogItemInfo],
    ) -> list[ProductRecommendation]:
        if not catalog_items:
            return []

        seen_ids: set[uuid.UUID] = set()
        recommendations: list[ProductRecommendation] = []

        for match in _PRODUCT_PATTERN.finditer(content):
            index = int(match.group(1))
            if index < 1 or index > len(catalog_items):
                continue

            item = catalog_items[index - 1]
            if item.id in seen_ids:
                continue

            seen_ids.add(item.id)
            recommendations.append(
                ProductRecommendation(
                    index=index,
                    catalog_item_id=item.id,
                    name=item.name,
                    sku=item.sku,
                    item_type=item.item_type,
                    url=item.url,
                    image_url=item.image_url,
                    text_recommendation=_format_recommendation(item),
                )
            )
            # Max 1 recommendation per response
            break

        return recommendations

    @staticmethod
    def strip_markers(content: str) -> str:
        return _PRODUCT_PATTERN.sub("", content)
```

- [ ] **Step 4: Register in `__init__.py`**

Add to `backend/app/services/__init__.py` exports:

```python
"ProductRecommendation": ("app.services.product_recommendation", "ProductRecommendation"),
"ProductRecommendationService": ("app.services.product_recommendation", "ProductRecommendationService"),
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_product_recommendation.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/product_recommendation.py backend/app/services/__init__.py backend/tests/unit/test_product_recommendation.py
git commit -m "feat(catalog): add ProductRecommendationService with [product:N] marker extraction"
```

---

## Task 7: Citation Enrichment

**Files:**
- Modify: `backend/tests/unit/test_citation_service.py`
- Modify: `backend/app/services/citation.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_citation_service.py`:

```python
class TestCitationPurchaseEnrichment:
    def test_citation_includes_purchase_url_when_catalog_active(self) -> None:
        source = SourceInfo(
            id=uuid.uuid4(),
            title="Clean Architecture",
            public_url="https://example.com/article",
            source_type="pdf",
            catalog_item_url="https://store.com/clean-arch",
            catalog_item_name="Clean Architecture Book",
            catalog_item_type="book",
            catalog_item_active=True,
        )
        chunk = _chunk(source_id=source.id)
        citations = CitationService.extract(
            "Answer [source:1]",
            [chunk],
            {source.id: source},
            10,
        )
        assert len(citations) == 1
        assert citations[0].purchase_url == "https://store.com/clean-arch"
        assert citations[0].purchase_title == "Clean Architecture Book"
        assert citations[0].catalog_item_type == "book"

    def test_citation_no_purchase_when_catalog_inactive(self) -> None:
        source = SourceInfo(
            id=uuid.uuid4(),
            title="Old Book",
            public_url=None,
            source_type="pdf",
            catalog_item_url="https://store.com/old",
            catalog_item_name="Old Book",
            catalog_item_type="book",
            catalog_item_active=False,
        )
        chunk = _chunk(source_id=source.id)
        citations = CitationService.extract(
            "Answer [source:1]",
            [chunk],
            {source.id: source},
            10,
        )
        assert len(citations) == 1
        assert citations[0].purchase_url is None

    def test_citation_no_purchase_when_no_catalog(self) -> None:
        source = SourceInfo(
            id=uuid.uuid4(),
            title="Article",
            public_url="https://blog.example.com",
            source_type="html",
        )
        chunk = _chunk(source_id=source.id)
        citations = CitationService.extract(
            "Answer [source:1]",
            [chunk],
            {source.id: source},
            10,
        )
        assert len(citations) == 1
        assert citations[0].purchase_url is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_citation_service.py::TestCitationPurchaseEnrichment -v
```

Expected: `TypeError: SourceInfo.__init__() got an unexpected keyword argument 'catalog_item_url'`

- [ ] **Step 3: Extend SourceInfo dataclass**

In `backend/app/services/citation.py`, extend `SourceInfo`:

```python
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
```

- [ ] **Step 4: Extend Citation dataclass**

Add fields after `text_citation`:

```python
purchase_url: str | None = None
purchase_title: str | None = None
catalog_item_type: str | None = None
```

Update `to_dict()` to include new fields:

```python
"purchase_url": self.purchase_url,
"purchase_title": self.purchase_title,
"catalog_item_type": self.catalog_item_type,
```

Update `from_dict()` to read new fields:

```python
purchase_url=value.get("purchase_url"),
purchase_title=value.get("purchase_title"),
catalog_item_type=value.get("catalog_item_type"),
```

- [ ] **Step 5: Add enrichment logic in extract()**

In `CitationService.extract()`, where `Citation` is constructed, compute purchase fields:

```python
purchase_url = None
purchase_title = None
cat_item_type = None
if source_info.catalog_item_active and source_info.catalog_item_url:
    purchase_url = source_info.catalog_item_url
    purchase_title = source_info.catalog_item_name
    cat_item_type = source_info.catalog_item_type
```

Pass `purchase_url=purchase_url, purchase_title=purchase_title, catalog_item_type=cat_item_type` to `Citation()`.

- [ ] **Step 6: Run all citation tests**

```bash
docker compose exec api python -m pytest tests/unit/test_citation_service.py -v
```

Expected: All tests PASS (existing tests should pass since new fields have defaults).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/citation.py backend/tests/unit/test_citation_service.py
git commit -m "feat(catalog): enrich citations with purchase links from catalog items"
```

---

## Task 8: Extend ContextAssembler

**Files:**
- Modify: `backend/tests/unit/test_context_assembler.py`
- Modify: `backend/app/services/context_assembler.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_context_assembler.py`:

```python
from app.services.catalog import CatalogItemInfo
from app.db.models.enums import CatalogItemType


def _catalog_item(
    *,
    sku: str = "BOOK-001",
    name: str = "Test Book",
    item_type: CatalogItemType = CatalogItemType.BOOK,
    url: str = "https://store.example.com",
) -> CatalogItemInfo:
    return CatalogItemInfo(
        id=uuid.uuid4(),
        sku=sku,
        name=name,
        item_type=item_type,
        url=url,
        image_url=None,
    )


class TestAvailableProductsLayer:
    def test_includes_available_products_when_catalog_present(self) -> None:
        items = [_catalog_item(sku="BOOK-001", name="My Book")]
        assembler = _assembler(catalog_items=items)
        result = assembler.assemble(
            chunks=[], query="test", source_map={},
        )
        system_msg = result.messages[0]["content"]
        assert "<available_products>" in system_msg
        assert "[product:1]" in system_msg
        assert "My Book" in system_msg
        assert "BOOK-001" in system_msg

    def test_omits_available_products_when_catalog_empty(self) -> None:
        assembler = _assembler(catalog_items=[])
        result = assembler.assemble(
            chunks=[], query="test", source_map={},
        )
        system_msg = result.messages[0]["content"]
        assert "<available_products>" not in system_msg
        assert "<product_instructions>" not in system_msg

    def test_omits_available_products_when_catalog_none(self) -> None:
        assembler = _assembler()
        result = assembler.assemble(
            chunks=[], query="test", source_map={},
        )
        system_msg = result.messages[0]["content"]
        assert "<available_products>" not in system_msg

    def test_product_instructions_included_with_catalog(self) -> None:
        items = [_catalog_item()]
        assembler = _assembler(catalog_items=items)
        result = assembler.assemble(
            chunks=[], query="test", source_map={},
        )
        system_msg = result.messages[0]["content"]
        assert "<product_instructions>" in system_msg
        assert "[product:N]" in system_msg

    def test_catalog_items_tracked_in_assembled_prompt(self) -> None:
        items = [_catalog_item()]
        assembler = _assembler(catalog_items=items)
        result = assembler.assemble(
            chunks=[], query="test", source_map={},
        )
        assert len(result.catalog_items_used) == 1

    def test_available_products_in_layer_token_counts(self) -> None:
        items = [_catalog_item()]
        assembler = _assembler(catalog_items=items)
        result = assembler.assemble(
            chunks=[], query="test", source_map={},
        )
        assert "available_products" in result.layer_token_counts
        assert result.layer_token_counts["available_products"] > 0
```

Note: update `_assembler()` helper to accept optional `catalog_items` parameter.

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_context_assembler.py::TestAvailableProductsLayer -v
```

Expected: Failures due to missing `catalog_items` parameter or missing `catalog_items_used` field.

- [ ] **Step 3: Extend ContextAssembler constructor**

In `backend/app/services/context_assembler.py`, add to `__init__()`:

```python
catalog_items: list[CatalogItemInfo] | None = None,
```

Store as `self._catalog_items = catalog_items or []`.

Add import at the top:

```python
from app.services.catalog import CatalogItemInfo
```

- [ ] **Step 4: Extend AssembledPrompt dataclass**

Add field:

```python
catalog_items_used: list[CatalogItemInfo] = field(default_factory=list)
```

Add import: `from dataclasses import dataclass, field`

- [ ] **Step 5: Add _build_available_products_layer() method**

Use the existing `_build_layer()` method (which wraps content in XML tags via `_wrap()`) — consistent with all other layers in the assembler:

```python
def _build_available_products_layer(self) -> PromptLayer | None:
    if not self._catalog_items:
        return None
    lines = [
        "The following products from the prototype's catalog are available.",
        "If a promotion context suggests mentioning a product and it is relevant",
        "to the current conversation, reference it using its [product:N] marker.",
        "Only recommend when naturally appropriate. Never force a recommendation.",
        "Maximum one product recommendation per response.",
        "",
    ]
    for i, item in enumerate(self._catalog_items, 1):
        lines.append(
            f'[product:{i}] "{item.name}" ({item.item_type.value}) — SKU: {item.sku}'
        )
    return self._build_layer("available_products", "\n".join(lines))
```

- [ ] **Step 6: Add _build_product_instructions_layer() method**

```python
_PRODUCT_INSTRUCTIONS = (
    "When recommending a product, place [product:N] after mentioning it.\n"
    "Do NOT generate URLs — the system substitutes real links.\n"
    "Do NOT recommend products not listed in available_products.\n"
    "If no product is relevant to the conversation, do not recommend anything.\n"
    "A recommendation should feel natural, like a real person mentioning\n"
    "something they genuinely find relevant — not like an advertisement."
)

def _build_product_instructions_layer(self) -> PromptLayer | None:
    if not self._catalog_items:
        return None
    return self._build_layer("product_instructions", _PRODUCT_INSTRUCTIONS)
```

- [ ] **Step 7: Wire layers into assemble()**

In the `assemble()` method, insert the new layers in the correct order:

1. After `promotions` layer → insert `available_products`
2. After `citation_instructions` layer → insert `product_instructions`

Add `catalog_items_used=list(self._catalog_items)` to the `AssembledPrompt` return.

Track both in `layer_token_counts`.

- [ ] **Step 8: Run all context assembler tests**

```bash
docker compose exec api python -m pytest tests/unit/test_context_assembler.py -v
```

Expected: All tests PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/context_assembler.py backend/tests/unit/test_context_assembler.py
git commit -m "feat(catalog): add available_products and product_instructions prompt layers"
```

---

## Task 9: SSE Products Event + DI + ChatService Integration

**Files:**
- Modify: `backend/app/api/chat.py` (SSE event)
- Modify: `backend/app/api/dependencies.py` (ContextAssembler DI)
- Modify: `backend/app/services/chat.py` (source_map, product extraction, persistence)
- Modify: `backend/app/db/models/dialogue.py` (products JSONB field)
- Modify: `backend/app/api/chat_schemas.py` (products in response/history)

This is the most interconnected task. Current architecture: `ContextAssembler` is created in `get_context_assembler()` at `backend/app/api/dependencies.py:98-111` and injected into `ChatService` via `get_chat_service()` at line 129. Catalog items MUST be loaded in the DI layer, not inside ChatService.

- [ ] **Step 1: Add `products` JSONB column to Message model**

In `backend/app/db/models/dialogue.py`, add after `content_type_spans` (line 96):

```python
products: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 2: Extend `get_context_assembler()` in dependencies.py**

Modify `backend/app/api/dependencies.py` — make `get_context_assembler` async, add session dependency to load catalog items:

```python
async def get_context_assembler(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    persona_context: Annotated[PersonaContext, Depends(get_persona_context)],
    promotions_service: Annotated[PromotionsService, Depends(get_promotions_service)],
) -> ContextAssembler:
    from app.services.catalog import CatalogService

    settings = request.app.state.settings

    # Load active catalog items for product recommendations
    from app.core.constants import DEFAULT_AGENT_ID

    catalog_service = CatalogService(session)
    active_items = await catalog_service.get_active_items(
        agent_id=DEFAULT_AGENT_ID,
    )
    catalog_item_infos = list(CatalogService.build_sku_map(active_items).values())

    return ContextAssembler(
        persona_context=persona_context,
        promotions_service=promotions_service,
        retrieval_context_budget=settings.retrieval_context_budget,
        max_citations=settings.max_citations_per_response,
        min_retrieved_chunks=settings.min_retrieved_chunks,
        max_promotions_per_response=settings.max_promotions_per_response,
        catalog_items=catalog_item_infos,
    )
```

Note: `get_chat_service` already depends on `get_context_assembler` via DI (line 129), so the assembled catalog items flow through automatically. No changes needed in `get_chat_service`.

- [ ] **Step 3: Add ChatStreamProducts dataclass to chat.py (API)**

In `backend/app/api/chat.py`, near existing `ChatStreamCitations`:

```python
@dataclass(slots=True, frozen=True)
class ChatStreamProducts:
    products: list[ProductRecommendation]
```

Add import:

```python
from app.services.product_recommendation import ProductRecommendation
```

- [ ] **Step 4: Add products SSE event formatting**

In the SSE formatting function/block where `ChatStreamCitations` is handled, add after it:

```python
if isinstance(event, ChatStreamProducts):
    return _format_sse(
        "products",
        {"products": [p.to_dict() for p in event.products]},
    )
```

- [ ] **Step 5: Extend _load_source_map() in ChatService**

In `backend/app/services/chat.py`, modify `_load_source_map()` to JOIN with catalog_items for citation enrichment:

```python
async def _load_source_map(self, source_ids: list[uuid.UUID]) -> dict[uuid.UUID, SourceInfo]:
    if not source_ids:
        return {}

    today = date.today()
    rows = await self._session.execute(
        select(
            Source.id,
            Source.title,
            Source.public_url,
            Source.source_type,
            CatalogItem.url.label("catalog_url"),
            CatalogItem.name.label("catalog_name"),
            CatalogItem.item_type.label("catalog_type"),
            CatalogItem.is_active.label("catalog_active"),
            CatalogItem.valid_from.label("catalog_valid_from"),
            CatalogItem.valid_until.label("catalog_valid_until"),
        )
        .outerjoin(CatalogItem, Source.catalog_item_id == CatalogItem.id)
        .where(
            Source.id.in_(source_ids),
            Source.deleted_at.is_(None),
        )
    )
    result = {}
    for row in rows:
        vf = row.catalog_valid_from.date() if isinstance(row.catalog_valid_from, datetime) else row.catalog_valid_from
        vu = row.catalog_valid_until.date() if isinstance(row.catalog_valid_until, datetime) else row.catalog_valid_until
        catalog_active = bool(
            row.catalog_active
            and (vf is None or vf <= today)
            and (vu is None or vu >= today)
        )
        result[row.id] = SourceInfo(
            id=row.id,
            title=row.title,
            public_url=row.public_url,
            source_type=row.source_type.value,
            catalog_item_url=row.catalog_url if catalog_active else None,
            catalog_item_name=row.catalog_name if catalog_active else None,
            catalog_item_type=row.catalog_type.value if catalog_active and row.catalog_type else None,
            catalog_item_active=catalog_active,
        )
    return result
```

Add imports:

```python
from datetime import date, datetime
from app.db.models.core import CatalogItem
```

- [ ] **Step 6: Extract product recommendations after LLM response**

In `ChatService`, after `CitationService.extract()` is called, add product extraction. Two paths need updating:

**Non-streaming path** (after line ~250 where `citations` is extracted from `llm_response.content`):

```python
from app.services.product_recommendation import ProductRecommendationService

products = ProductRecommendationService.extract(
    llm_response.content,
    assembled.catalog_items_used,
)
# Strip [product:N] markers from content before persisting
final_content = ProductRecommendationService.strip_markers(llm_response.content)
```

Then pass `content=final_content` and `products=[p.to_dict() for p in products] if products else None` to `_persist_message()` (line ~258).

**Streaming path** (after line ~462 where `citations` is extracted from `assistant_message.content`):

```python
products = ProductRecommendationService.extract(
    assistant_message.content,
    assembled.catalog_items_used,
)
assistant_message.content = ProductRecommendationService.strip_markers(assistant_message.content)
```

- [ ] **Step 7: Persist products in message record**

**Non-streaming:** Add `products` parameter to `_persist_message()` call at line ~258:

```python
products=[p.to_dict() for p in products] if products else None,
```

**Streaming:** Set directly on the message object (same pattern as `assistant_message.citations` at line ~467):

```python
assistant_message.products = [p.to_dict() for p in products] if products else None
```

**Update `_persist_message()` signature** at line 578 — add parameter:

```python
products: list[dict[str, object]] | None = None,
```

And in the `Message()` constructor at line 597, add:

```python
products=products,
```

- [ ] **Step 8: Emit products SSE event in streaming path**

In the streaming path, after emitting citations, emit products if any:

```python
if products:
    yield ChatStreamProducts(products=products)
```

- [ ] **Step 9: Extend chat_schemas.py for products in responses**

In `backend/app/api/chat_schemas.py`:

Add `ProductRecommendationResponse` schema:

```python
class ProductRecommendationResponse(BaseModel):
    index: int
    catalog_item_id: uuid.UUID
    name: str
    sku: str
    item_type: str
    url: str | None = None
    image_url: str | None = None
    text_recommendation: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProductRecommendationResponse:
        return cls(
            index=value["index"],
            catalog_item_id=uuid.UUID(str(value["catalog_item_id"])),
            name=value["name"],
            sku=value["sku"],
            item_type=value["item_type"],
            url=value.get("url"),
            image_url=value.get("image_url"),
            text_recommendation=value["text_recommendation"],
        )
```

Add `products` field to `MessageResponse`:

```python
products: list[ProductRecommendationResponse] | None = None
```

Update `MessageResponse.from_message()` to parse products (same pattern as citations):

```python
products=_parse_products(message.products),
```

Add `products` to `MessageInHistory` the same way.

Add `purchase_url`, `purchase_title`, `catalog_item_type` to `CitationResponse`:

```python
purchase_url: str | None = None
purchase_title: str | None = None
catalog_item_type: str | None = None
```

Update `CitationResponse.from_dict()` to read new fields.

- [ ] **Step 10: Persist recommended_product_ids via Message model**

ProxyMind currently persists audit data on the `Message` model itself (not a separate audit table — that's S7-02). The relevant fields are `source_ids` (line 89), `citations` (line 93), `content_type_spans` (line 94) on `backend/app/db/models/dialogue.py`. Products are now stored in the new `products: JSONB` field added in Step 1.

The product IDs are already captured by persisting `products` in Step 7. For additional audit convenience, include product IDs in the existing `source_ids`-like pattern. No separate audit metadata structure is needed — the `products` JSONB field on Message IS the audit record for recommendations, alongside `citations` for knowledge references.

Verify: after a response with `[product:N]`, the `messages` row contains both `citations` (knowledge) and `products` (recommendations) as JSONB arrays.

- [ ] **Step 11: Run existing chat tests to verify no regressions**

```bash
docker compose exec api python -m pytest tests/ -v -k "chat" --timeout=60
```

Expected: All existing tests PASS. The new `products` field has default `None`, so existing test fixtures remain valid.

- [ ] **Step 12: Commit**

```bash
git add backend/app/api/chat.py backend/app/api/chat_schemas.py backend/app/api/dependencies.py backend/app/services/chat.py backend/app/db/models/dialogue.py
git commit -m "feat(catalog): wire citation enrichment, product recommendations, SSE event, and persistence"
```

---

## Task 10: Update PROMOTIONS.md

**Files:**
- Modify: `config/PROMOTIONS.md`

- [ ] **Step 1: Add Catalog item metadata to existing promotions**

Update `config/PROMOTIONS.md`:

```markdown
## New Book: "AI in Practice"

- **Priority:** high
- **Valid from:** 2026-01-15
- **Valid to:** 2026-06-30
- **Catalog item:** AI-PRACTICE-2026
- **Context:** When the conversation touches AI, machine learning, or practical applications of neural networks.

My new book "AI in Practice" covers real-world applications of modern AI systems.
Available at the online store with a 20% launch discount.

## Upcoming Conference: Tech Summit 2026

- **Priority:** medium
- **Valid from:** 2026-03-01
- **Valid to:** 2026-04-15
- **Catalog item:** TECHSUMMIT-2026
- **Context:** When discussing conferences, networking, or professional development.

Join me at Tech Summit 2026 in Berlin. Early bird tickets available until April 1.
```

- [ ] **Step 2: Commit**

```bash
git add config/PROMOTIONS.md
git commit -m "feat(catalog): add Catalog item SKU references to PROMOTIONS.md"
```

---

## Task 11: Integration Smoke Test

**Files:**
- Manual testing via Docker

- [ ] **Step 1: Rebuild and start services**

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```

- [ ] **Step 2: Create catalog items matching PROMOTIONS.md SKUs**

```bash
curl -s -X POST http://localhost:8000/api/admin/catalog \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "AI-PRACTICE-2026",
    "name": "AI in Practice",
    "item_type": "book",
    "url": "https://store.example.com/ai-practice"
  }' | python -m json.tool

curl -s -X POST http://localhost:8000/api/admin/catalog \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "TECHSUMMIT-2026",
    "name": "Tech Summit 2026 Ticket",
    "item_type": "event",
    "url": "https://techsummit2026.example.com/tickets"
  }' | python -m json.tool
```

Expected: Both return 201 with item data.

- [ ] **Step 3: Verify catalog list**

```bash
curl -s http://localhost:8000/api/admin/catalog | python -m json.tool
```

Expected: Both items in the list, `total: 2`.

- [ ] **Step 4: Upload a source and link to catalog item**

Upload a test markdown file linked to the book catalog item, then verify the source shows `catalog_item_id`.

- [ ] **Step 5: Run full test suite**

```bash
docker compose exec api python -m pytest tests/ -v --timeout=120
```

Expected: All tests PASS.

- [ ] **Step 6: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(catalog): address integration test findings"
```

---

## Summary

| Task | Component | Files | Est. Steps |
|------|-----------|-------|-----------|
| 1 | Migration + Model (sku, FK, products JSONB) | 3 files | 5 |
| 2 | Pydantic Schemas | 2 files | 3 |
| 3 | CatalogService | 3 files | 6 |
| 4 | Catalog API Endpoints | 2 files | 10 |
| 5 | PromotionsService Extension | 2 files | 6 |
| 6 | ProductRecommendationService | 3 files | 6 |
| 7 | Citation Enrichment | 2 files | 7 |
| 8 | ContextAssembler Extension | 2 files | 9 |
| 9 | SSE + DI + ChatService + Persistence | 5 files | 12 |
| 10 | PROMOTIONS.md Update | 1 file | 2 |
| 11 | Integration Smoke Test | 0 files | 6 |
| **Total** | | **25 files** | **72 steps** |
