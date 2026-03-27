## Purpose

Automatic enrichment of knowledge citations with purchase links when the cited source has an active linked catalog item. This is one of two independent commercial link delivery mechanisms (the other being product recommendations via `[product:N]` markers). Citation enrichment is automatic and knowledge-driven: source cited → purchase link added. No configuration needed beyond the source-catalog link. Introduced by S6-01.

## ADDED Requirements

### Requirement: Automatic enrichment trigger

When building a citation, the system SHALL automatically enrich it with purchase link data if the cited source has an active linked catalog item. The trigger is the existence of a source ↔ catalog_item link where the catalog item is active, not expired, and has a non-null URL. No manual configuration or per-request flags are needed.

#### Scenario: Citation enriched when source has active catalog item

- **WHEN** a citation is built for a source that has `catalog_item_id` pointing to an active catalog item with `url = "https://store.com/clean-arch"`
- **THEN** the citation SHALL include `purchase_url = "https://store.com/clean-arch"`, `purchase_title` from the catalog item name, and `catalog_item_type` from the catalog item type

#### Scenario: No enrichment when source has no catalog item

- **WHEN** a citation is built for a source with `catalog_item_id = NULL`
- **THEN** `purchase_url`, `purchase_title`, and `catalog_item_type` SHALL all be `None`

---

### Requirement: Inactive and expired items excluded from enrichment

Catalog items that are inactive (`is_active=false`) or expired (`valid_until < today`) SHALL NOT trigger citation enrichment. The `catalog_item_active` flag on `SourceInfo` SHALL be `False` for such items, and the enrichment logic SHALL check this flag before populating purchase fields.

#### Scenario: Inactive catalog item does not enrich

- **WHEN** a citation is built for a source linked to a catalog item with `is_active=false`
- **THEN** `purchase_url` SHALL be `None`
- **AND** `purchase_title` SHALL be `None`
- **AND** `catalog_item_type` SHALL be `None`

#### Scenario: Expired catalog item does not enrich

- **WHEN** a citation is built for a source linked to a catalog item with `valid_until` before today
- **THEN** `purchase_url` SHALL be `None`

#### Scenario: Active item within date range enriches

- **WHEN** a citation is built for a source linked to an active catalog item where `valid_from <= today <= valid_until`
- **THEN** the citation SHALL include purchase fields from the catalog item

---

### Requirement: Citation priority over commercial link

The citation SHALL remain knowledge-first. The purchase link is supplementary metadata, not a replacement for the citation's source information. `source_title`, `anchor`, `text_citation`, and `url` SHALL remain the primary citation fields. `purchase_url`, `purchase_title`, and `catalog_item_type` are additional fields. The frontend decides how to render them (e.g., a "Buy" button next to the citation).

#### Scenario: Knowledge fields remain primary

- **WHEN** a citation is enriched with purchase data
- **THEN** `source_title`, `anchor`, `text_citation`, and `url` SHALL remain unchanged
- **AND** `purchase_url` and `purchase_title` SHALL be additional, separate fields

#### Scenario: Citation without purchase data is still complete

- **WHEN** a citation has no linked catalog item
- **THEN** the citation SHALL be fully valid with `source_title`, `anchor`, `text_citation`, `url`
- **AND** `purchase_url` SHALL be `None` (not an error, not a warning)

---

### Requirement: Source map population with catalog data

When loading the source map for citation building, the query SHALL LEFT JOIN `catalog_items` on `sources.catalog_item_id = catalog_items.id`. The join SHALL filter catalog items by `is_active = true` and date validity (`valid_from <= today` or null, `valid_until >= today` or null). The resulting `SourceInfo` objects SHALL include catalog item fields (`catalog_item_url`, `catalog_item_name`, `catalog_item_type`, `catalog_item_active`).

#### Scenario: Source map includes catalog data for active item

- **WHEN** the source map is loaded and a source has `catalog_item_id` pointing to an active, non-expired catalog item
- **THEN** `SourceInfo.catalog_item_url` SHALL be the catalog item's URL
- **AND** `SourceInfo.catalog_item_name` SHALL be the catalog item's name
- **AND** `SourceInfo.catalog_item_type` SHALL be the catalog item's type
- **AND** `SourceInfo.catalog_item_active` SHALL be `True`

#### Scenario: Source map excludes inactive catalog data

- **WHEN** the source map is loaded and a source has `catalog_item_id` pointing to an inactive catalog item
- **THEN** `SourceInfo.catalog_item_active` SHALL be `False`
- **AND** `SourceInfo.catalog_item_url` SHALL be `None` (or the raw value, but enrichment will not trigger)

#### Scenario: Source without catalog link has default values

- **WHEN** the source map is loaded and a source has `catalog_item_id = NULL`
- **THEN** `SourceInfo.catalog_item_url` SHALL be `None`
- **AND** `SourceInfo.catalog_item_name` SHALL be `None`
- **AND** `SourceInfo.catalog_item_type` SHALL be `None`
- **AND** `SourceInfo.catalog_item_active` SHALL be `False`

---

### Requirement: Catalog item without URL produces recommendation without link

When a catalog item has no `url` (null), the enrichment SHALL still set `purchase_title` and `catalog_item_type` if the item is active, but `purchase_url` SHALL be `None`. This supports offline products (e.g., an in-person event with no purchase page).

#### Scenario: Active catalog item with null URL

- **WHEN** a citation is built for a source linked to an active catalog item with `url=None`
- **THEN** `purchase_url` SHALL be `None`
- **AND** `purchase_title` SHALL still be populated with the catalog item name
- **AND** `catalog_item_type` SHALL still be populated

---

### Requirement: Enriched citation in persisted and SSE formats

The enriched citation fields (`purchase_url`, `purchase_title`, `catalog_item_type`) SHALL be included in both the persisted `Message.citations` JSONB and the SSE `citations` event payload. Fields SHALL be `null` when no catalog item is linked or the item is inactive/expired.

#### Scenario: Enriched citation in SSE event

- **WHEN** the SSE `citations` event is emitted with enriched citations
- **THEN** each citation object SHALL include `purchase_url`, `purchase_title`, `catalog_item_type` fields (nullable)

#### Scenario: Enriched citation in persisted message

- **WHEN** `Message.citations` is stored after enrichment
- **THEN** each citation dict SHALL include `purchase_url`, `purchase_title`, `catalog_item_type` keys

#### Scenario: Null purchase fields when no enrichment

- **WHEN** a citation is persisted or emitted without enrichment
- **THEN** `purchase_url`, `purchase_title`, and `catalog_item_type` SHALL all be `null` in the serialized output
