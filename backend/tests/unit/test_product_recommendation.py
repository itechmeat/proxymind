from __future__ import annotations

import uuid

from app.db.models.enums import CatalogItemType
from app.services.catalog import CatalogItemInfo
from app.services.product_recommendation import ProductRecommendationService


def _catalog_item(sku: str, *, name: str | None = None) -> CatalogItemInfo:
    return CatalogItemInfo(
        id=uuid.uuid7(),
        sku=sku,
        name=name or sku,
        item_type=CatalogItemType.BOOK,
        url=f"https://example.com/{sku.lower()}",
        image_url=f"https://example.com/{sku.lower()}.png",
    )


def test_extract_single_marker() -> None:
    items = [_catalog_item("BOOK-001", name="AI in Practice")]

    result = ProductRecommendationService.extract("Check this [product:1]", items)

    assert len(result) == 1
    assert isinstance(result[0].catalog_item_id, uuid.UUID)
    assert result[0].sku == "BOOK-001"
    assert result[0].text_recommendation == "AI in Practice (book)"


def test_extract_returns_at_most_one_recommendation() -> None:
    items = [_catalog_item("BOOK-001"), _catalog_item("BOOK-002")]

    result = ProductRecommendationService.extract(
        "First [product:1], then [product:2]",
        items,
    )

    assert len(result) == 1
    assert result[0].sku == "BOOK-001"


def test_extract_skips_invalid_indices() -> None:
    items = [_catalog_item("BOOK-001")]

    assert ProductRecommendationService.extract("Bad [product:0]", items) == []
    assert ProductRecommendationService.extract("Bad [product:2]", items) == []


def test_extract_uses_first_valid_after_invalid() -> None:
    items = [_catalog_item("BOOK-001")]

    result = ProductRecommendationService.extract(
        "Ignore [product:9], keep [product:1]",
        items,
    )

    assert len(result) == 1
    assert result[0].sku == "BOOK-001"


def test_extract_returns_empty_without_markers_or_catalog() -> None:
    items = [_catalog_item("BOOK-001")]

    assert ProductRecommendationService.extract("No marker here", items) == []
    assert ProductRecommendationService.extract("[product:1]", []) == []


def test_strip_markers_removes_all_product_references() -> None:
    result = ProductRecommendationService.strip_markers(
        "Book [product:1] and event [product:2]."
    )

    assert result == "Book and event."


def test_strip_markers_preserves_source_markers() -> None:
    result = ProductRecommendationService.strip_markers(
        "Answer [source:1] with recommendation [product:1]."
    )

    assert result == "Answer [source:1] with recommendation."


def test_to_dict_and_from_dict_round_trip() -> None:
    recommendation = ProductRecommendationService.extract(
        "Check this [product:1]",
        [_catalog_item("BOOK-001", name="AI in Practice")],
    )[0]

    restored = type(recommendation).from_dict(recommendation.to_dict())

    assert restored == recommendation
