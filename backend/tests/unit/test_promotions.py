from __future__ import annotations

import datetime

from app.services.promotions import PromotionsService

VALID_PROMOTIONS_MD = """\
## Book Launch

- **Priority:** high
- **Valid from:** 2020-01-01
- **Valid to:** 2099-12-31
- **Context:** When discussing books or reading.

Check out my new book about AI.

## Old Conference

- **Priority:** medium
- **Valid from:** 2020-01-01
- **Valid to:** 2020-06-30
- **Context:** When discussing events.

This conference already happened.

## Future Event

- **Priority:** low
- **Valid from:** 2099-01-01
- **Valid to:** 2099-12-31
- **Context:** Future event hint.

This event is far in the future.

## Always Active

- **Priority:** low

This promotion has no date bounds.
"""


def test_parse_extracts_all_sections() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promotions = service.parse()
    assert len(promotions) == 4
    assert promotions[0].title == "Book Launch"
    assert promotions[0].priority == "high"
    assert promotions[0].body == "Check out my new book about AI."
    assert promotions[0].catalog_item_sku is None


def test_parse_extracts_dates() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promotions = service.parse()
    assert promotions[0].valid_from == datetime.date(2020, 1, 1)
    assert promotions[0].valid_to == datetime.date(2099, 12, 31)


def test_parse_missing_dates_are_none() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promotions = service.parse()
    always_active = [promotion for promotion in promotions if promotion.title == "Always Active"][0]
    assert always_active.valid_from is None
    assert always_active.valid_to is None


def test_parse_missing_context_is_empty() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promotions = service.parse()
    always_active = [promotion for promotion in promotions if promotion.title == "Always Active"][0]
    assert always_active.context == ""


def test_filter_removes_expired() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    titles = [promotion.title for promotion in service.get_active(today=datetime.date(2025, 6, 15))]
    assert "Old Conference" not in titles
    assert "Book Launch" in titles


def test_filter_removes_not_yet_active() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    titles = [promotion.title for promotion in service.get_active(today=datetime.date(2025, 6, 15))]
    assert "Future Event" not in titles


def test_filter_keeps_no_date_bounds() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    titles = [promotion.title for promotion in service.get_active(today=datetime.date(2025, 6, 15))]
    assert "Always Active" in titles


def test_sort_by_priority() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    active = service.get_active(today=datetime.date(2025, 6, 15))
    assert active[0].priority == "high"
    assert active[1].priority == "low"


def test_sort_keeps_original_order_within_same_priority() -> None:
    promotions_text = """\
## First Low

- **Priority:** low

First body.

## Second Low

- **Priority:** low

Second body.
"""

    service = PromotionsService(promotions_text=promotions_text)

    active = service.get_active(today=datetime.date(2025, 6, 15))

    assert [promotion.title for promotion in active] == ["First Low", "Second Low"]


def test_select_top_n() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    selected = service.get_active(today=datetime.date(2025, 6, 15), max_promotions=1)
    assert len(selected) == 1
    assert selected[0].title == "Book Launch"


def test_empty_text_returns_empty_list() -> None:
    service = PromotionsService(promotions_text="")
    assert service.get_active() == []


def test_invalid_priority_defaults_to_low() -> None:
    service = PromotionsService(
        promotions_text="## Test\n\n- **Priority:** urgent\n\nBody text here."
    )
    promotions = service.parse()
    assert promotions[0].priority == "low"


def test_invalid_date_skips_promotion() -> None:
    service = PromotionsService(
        promotions_text="## Test\n\n- **Priority:** high\n- **Valid to:** not-a-date\n\nBody."
    )
    assert service.parse() == []


def test_empty_body_skips_promotion() -> None:
    service = PromotionsService(promotions_text="## No Body\n\n- **Priority:** high\n")
    assert service.parse() == []


def test_file_loading_from_path(tmp_path) -> None:
    promo_file = tmp_path / "PROMOTIONS.md"
    promo_file.write_text("## Test Promo\n\n- **Priority:** high\n\nA body.", encoding="utf-8")
    service = PromotionsService.from_file(promo_file)
    promotions = service.parse()
    assert len(promotions) == 1
    assert promotions[0].title == "Test Promo"


def test_file_not_found_returns_empty(tmp_path) -> None:
    service = PromotionsService.from_file(tmp_path / "missing.md")
    assert service.get_active() == []


def test_parse_catalog_item_metadata() -> None:
    service = PromotionsService(
        promotions_text="## Promo\n\n- **Catalog item:** BOOK-001\n\nBody."
    )

    promotions = service.parse()

    assert promotions[0].catalog_item_sku == "BOOK-001"


def test_parse_missing_catalog_item_returns_none() -> None:
    service = PromotionsService(promotions_text="## Promo\n\nBody.")

    promotions = service.parse()

    assert promotions[0].catalog_item_sku is None


def test_parse_catalog_item_strips_whitespace() -> None:
    service = PromotionsService(
        promotions_text="## Promo\n\n- **Catalog item:**   BOOK-002  \n\nBody."
    )

    promotions = service.parse()

    assert promotions[0].catalog_item_sku == "BOOK-002"
