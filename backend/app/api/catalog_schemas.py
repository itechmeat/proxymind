from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, UrlConstraints

from app.db.models.enums import CatalogItemType, SourceStatus, SourceType


class CatalogItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    item_type: CatalogItemType
    url: Annotated[AnyHttpUrl, UrlConstraints(max_length=2048)] | None = None
    image_url: Annotated[AnyHttpUrl, UrlConstraints(max_length=2048)] | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class CatalogItemUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    item_type: CatalogItemType | None = None
    url: Annotated[AnyHttpUrl, UrlConstraints(max_length=2048)] | None = None
    image_url: Annotated[AnyHttpUrl, UrlConstraints(max_length=2048)] | None = None
    is_active: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


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


class LinkedSourceInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: SourceStatus


class CatalogItemDetail(CatalogItemResponse):
    linked_sources: list[LinkedSourceInfo]


class CatalogItemListResponse(BaseModel):
    items: list[CatalogItemResponse]
    total: int


class SourceUpdateRequest(BaseModel):
    catalog_item_id: uuid.UUID | None = None
