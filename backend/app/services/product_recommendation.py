from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProductRecommendation:
        return cls(
            index=value["index"],
            catalog_item_id=uuid.UUID(str(value["catalog_item_id"])),
            name=value["name"],
            sku=value["sku"],
            item_type=CatalogItemType(value["item_type"]),
            url=value.get("url"),
            image_url=value.get("image_url"),
            text_recommendation=value["text_recommendation"],
        )

    @classmethod
    def from_catalog_item(cls, index: int, item: CatalogItemInfo) -> ProductRecommendation:
        return cls(
            index=index,
            catalog_item_id=item.id,
            name=item.name,
            sku=item.sku,
            item_type=item.item_type,
            url=item.url,
            image_url=item.image_url,
            text_recommendation=f"{item.name} ({item.item_type.value})",
        )

    def to_dict(self) -> dict[str, Any]:
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


class ProductRecommendationService:
    @staticmethod
    def extract(
        content: str,
        catalog_items: list[CatalogItemInfo],
    ) -> list[ProductRecommendation]:
        if not catalog_items:
            return []

        seen_catalog_item_ids: set[uuid.UUID] = set()
        for match in _PRODUCT_PATTERN.finditer(content):
            index = int(match.group(1))
            if index < 1 or index > len(catalog_items):
                continue

            item = catalog_items[index - 1]
            catalog_item_id = item.id
            if catalog_item_id in seen_catalog_item_ids:
                continue

            seen_catalog_item_ids.add(catalog_item_id)
            return [ProductRecommendation.from_catalog_item(index, item)]

        return []

    @staticmethod
    def strip_markers(content: str) -> str:
        cleaned = _PRODUCT_PATTERN.sub("", content)
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"([([{])\s+", r"\1", cleaned)
        cleaned = re.sub(r"\s+([)\]}])", r"\1", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
