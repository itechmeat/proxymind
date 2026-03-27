## Purpose

Admin API for catalog item management: CRUD endpoints, SKU uniqueness, source linking via PATCH, soft delete, filtering, and pagination. The catalog stores products that the twin's prototype offers (books, courses, events, merch). One twin = one prototype = small catalog. Introduced by S6-01.

## ADDED Requirements

### Requirement: CatalogItem SKU field

The `CatalogItem` model SHALL have a `sku` field of type `String(64)`, unique, not null, and indexed (`ix_catalog_items_sku`). SKU is the human-readable identifier used for matching catalog items to PROMOTIONS.md entries. Existing rows (if any at migration time) SHALL be backfilled with `'LEGACY-' || id::text` before the unique index is created.

#### Scenario: SKU field present and unique

- **WHEN** a `CatalogItem` is inspected in the database
- **THEN** it SHALL have a non-null `sku` field of at most 64 characters
- **AND** no two catalog items SHALL share the same `sku` value

#### Scenario: Legacy backfill during migration

- **WHEN** the migration runs and existing `CatalogItem` rows have no `sku` value
- **THEN** each row SHALL receive `sku = 'LEGACY-' || id::text` (full UUID)
- **AND** the unique index SHALL be created after backfill completes without violation

---

### Requirement: Create catalog item

The system SHALL provide a `POST /api/admin/catalog` endpoint that creates a new catalog item. The request body SHALL conform to the `CatalogItemCreate` schema: `sku` (required, 1-64 chars), `name` (required, 1-255 chars), `description` (optional, max 2000 chars), `item_type` (required: book/course/event/merch/other), `url` (optional, max 2048 chars), `image_url` (optional, max 2048 chars), `valid_from` (optional datetime), `valid_until` (optional datetime). The endpoint SHALL return 201 with the created item on success.

#### Scenario: Create catalog item with unique SKU

- **WHEN** `POST /api/admin/catalog` is called with valid payload including `sku: "BOOK-001"`, `name: "AI in Practice"`, `item_type: "book"`
- **THEN** the system SHALL create the item and return 201 with the full item data including `id`, `sku`, `is_active`, `created_at`, `updated_at`

#### Scenario: Duplicate SKU rejected

- **WHEN** `POST /api/admin/catalog` is called with a `sku` that already exists in the database
- **THEN** the system SHALL return 409 Conflict with a clear error message indicating the SKU collision

#### Scenario: Missing required field rejected

- **WHEN** `POST /api/admin/catalog` is called without a `sku` or `name` or `item_type` field
- **THEN** the system SHALL return 422 Unprocessable Entity with validation details

#### Scenario: SKU length constraint enforced

- **WHEN** `POST /api/admin/catalog` is called with a `sku` exceeding 64 characters
- **THEN** the system SHALL return 422 Unprocessable Entity

---

### Requirement: List catalog items

The system SHALL provide a `GET /api/admin/catalog` endpoint that returns a paginated, filtered list of catalog items. Query parameters: `item_type` (optional filter by CatalogItemType), `is_active` (default `true`), `limit` (default 20, max 100), `offset` (default 0). The response SHALL contain `items` (array of `CatalogItemResponse`) and `total` (int count matching filters). Items SHALL be ordered by `created_at` descending. Soft-deleted items (non-null `deleted_at`) SHALL always be excluded.

#### Scenario: List active items with default parameters

- **WHEN** `GET /api/admin/catalog` is called with no query parameters
- **THEN** the response SHALL contain only active (`is_active=true`), non-deleted catalog items
- **AND** items SHALL be ordered by `created_at` descending
- **AND** `total` SHALL reflect the count of matching items

#### Scenario: Filter by item_type

- **WHEN** `GET /api/admin/catalog?item_type=book` is called
- **THEN** the response SHALL contain only catalog items with `item_type=book`

#### Scenario: Pagination with limit and offset

- **WHEN** `GET /api/admin/catalog?limit=2&offset=1` is called and 5 active items exist
- **THEN** `items` SHALL contain at most 2 items starting from position 1
- **AND** `total` SHALL be 5

#### Scenario: List inactive items only

- **WHEN** `GET /api/admin/catalog?is_active=false` is called
- **THEN** the response SHALL contain only inactive (`is_active=false`) catalog items (excluding soft-deleted)
- **AND** active items SHALL NOT appear in the result

---

### Requirement: Get catalog item detail

The system SHALL provide a `GET /api/admin/catalog/:id` endpoint that returns a single catalog item with its linked sources. The response SHALL conform to `CatalogItemDetail`: all `CatalogItemResponse` fields plus `linked_sources_count` (int) and `linked_sources` (array of `LinkedSourceInfo` with `id`, `title`, `source_type`, `status`). Only non-deleted sources SHALL be included in `linked_sources`.

#### Scenario: Retrieve existing catalog item with linked sources

- **WHEN** `GET /api/admin/catalog/:id` is called with a valid catalog item ID that has 2 linked sources (1 active, 1 deleted)
- **THEN** the response SHALL include the full catalog item data
- **AND** `linked_sources` SHALL contain 1 entry (the non-deleted source)
- **AND** `linked_sources_count` SHALL be 1

#### Scenario: Catalog item not found

- **WHEN** `GET /api/admin/catalog/:id` is called with a non-existent or soft-deleted ID
- **THEN** the system SHALL return 404 Not Found

---

### Requirement: Update catalog item (partial)

The system SHALL provide a `PATCH /api/admin/catalog/:id` endpoint that applies partial updates. The request body SHALL conform to `CatalogItemUpdate` where all fields are optional. Only fields present in the request body SHALL be updated (using Pydantic `exclude_unset`). The `sku` field MAY be updated; if the new SKU already exists, the system SHALL return 409 Conflict.

#### Scenario: Partial update changes only provided fields

- **WHEN** `PATCH /api/admin/catalog/:id` is called with body `{"name": "Updated Name"}`
- **THEN** only the `name` field SHALL be updated
- **AND** all other fields SHALL remain unchanged
- **AND** the response SHALL include the full updated item

#### Scenario: SKU update with collision rejected

- **WHEN** `PATCH /api/admin/catalog/:id` is called with `{"sku": "EXISTING-SKU"}` and another item already has that SKU
- **THEN** the system SHALL return 409 Conflict

#### Scenario: Empty update body is a no-op

- **WHEN** `PATCH /api/admin/catalog/:id` is called with an empty body `{}`
- **THEN** no fields SHALL be changed
- **AND** the response SHALL return the item as-is

#### Scenario: Update non-existent item

- **WHEN** `PATCH /api/admin/catalog/:id` is called with a non-existent or soft-deleted ID
- **THEN** the system SHALL return 404 Not Found

---

### Requirement: Soft delete catalog item

The system SHALL provide a `DELETE /api/admin/catalog/:id` endpoint that performs a soft delete: setting `deleted_at` to the current timestamp and `is_active` to `false`. Soft delete does NOT nullify `source.catalog_item_id` — the FK remains intact so that links can be restored if the item is re-activated. Citation enrichment and product recommendations are disabled by application-level filtering (`is_active` and `deleted_at` checks in `_load_source_map` and `get_active_items`). The FK `ON DELETE SET NULL` is a safety net for potential hard deletes only, not for the soft-delete workflow.

#### Scenario: Soft delete sets deleted_at and deactivates

- **WHEN** `DELETE /api/admin/catalog/:id` is called for an existing active item
- **THEN** the item SHALL have `deleted_at` set to the current timestamp
- **AND** `is_active` SHALL be set to `false`
- **AND** the item SHALL no longer appear in list queries

#### Scenario: Soft delete preserves source links but disables enrichment

- **WHEN** a catalog item with linked sources is soft-deleted
- **THEN** `source.catalog_item_id` SHALL remain unchanged (FK is NOT nullified — preserves audit context)
- **AND** citation enrichment SHALL no longer include purchase links (application-level `is_active` filtering)
- **AND** the catalog item SHALL not appear in `available_products` prompt layer

#### Scenario: Delete non-existent item

- **WHEN** `DELETE /api/admin/catalog/:id` is called with a non-existent or already soft-deleted ID
- **THEN** the system SHALL return 404 Not Found

---

### Requirement: Source re-linking via PATCH

The system SHALL provide a `PATCH /api/admin/sources/:id` endpoint that allows linking or unlinking a source to a catalog item. The request body SHALL use the `exclude_unset` Pydantic pattern: if `catalog_item_id` is absent from the body, it is not changed; if explicitly `null`, it unlinks the source; if a valid UUID, it links to that catalog item. The system SHALL verify the catalog item exists before linking.

#### Scenario: Link source to catalog item

- **WHEN** `PATCH /api/admin/sources/:id` is called with `{"catalog_item_id": "<valid-uuid>"}`
- **AND** the catalog item exists and is not deleted
- **THEN** `source.catalog_item_id` SHALL be set to the given UUID
- **AND** the response SHALL return the updated source

#### Scenario: Unlink source from catalog item

- **WHEN** `PATCH /api/admin/sources/:id` is called with `{"catalog_item_id": null}`
- **THEN** `source.catalog_item_id` SHALL be set to NULL
- **AND** the response SHALL return the updated source

#### Scenario: Link to non-existent catalog item rejected

- **WHEN** `PATCH /api/admin/sources/:id` is called with a `catalog_item_id` that does not exist or is soft-deleted
- **THEN** the system SHALL return 404 Not Found with detail "Catalog item not found"

#### Scenario: Source not found

- **WHEN** `PATCH /api/admin/sources/:id` is called with a non-existent or deleted source ID
- **THEN** the system SHALL return 404 Not Found with detail "Source not found"

#### Scenario: Empty body is a no-op

- **WHEN** `PATCH /api/admin/sources/:id` is called with an empty body `{}`
- **THEN** no fields SHALL be changed
- **AND** the response SHALL return the source as-is

---

### Requirement: Active item filtering with date validity

The `CatalogService` SHALL provide a `filter_active()` method that filters catalog items by `is_active` status and date validity. Items with `is_active=false` SHALL be excluded. Items with `valid_from` after today SHALL be excluded (not yet valid). Items with `valid_until` before today SHALL be excluded (expired). Items with null date bounds SHALL be treated as unbounded (always valid on that side). The method SHALL safely handle `datetime` to `date` conversion since the DB model stores `valid_from`/`valid_until` as `datetime`.

#### Scenario: Inactive items excluded

- **WHEN** `filter_active()` is called with items where one has `is_active=false`
- **THEN** the inactive item SHALL NOT appear in the result

#### Scenario: Expired items excluded

- **WHEN** today is 2026-03-27 and an item has `valid_until=datetime(2026, 1, 1)`
- **THEN** `filter_active(today=date(2026, 3, 27))` SHALL NOT include that item

#### Scenario: Not-yet-valid items excluded

- **WHEN** today is 2026-03-27 and an item has `valid_from=datetime(2026, 6, 1)`
- **THEN** `filter_active(today=date(2026, 3, 27))` SHALL NOT include that item

#### Scenario: Items without date bounds always active

- **WHEN** an item has `valid_from=None` and `valid_until=None` and `is_active=true`
- **THEN** `filter_active()` SHALL include that item regardless of the current date

#### Scenario: Datetime-to-date conversion handled safely

- **WHEN** an item has `valid_until=datetime(2026, 3, 27, 23, 59, 59)` and today is `date(2026, 3, 27)`
- **THEN** the comparison SHALL convert datetime to date before checking
- **AND** the item SHALL be included (valid_until date equals today)

---

### Requirement: SKU map for prompt assembly

The `CatalogService` SHALL provide a `build_sku_map()` static method that builds a `dict[str, CatalogItemInfo]` mapping SKU strings to lightweight `CatalogItemInfo` dataclasses. The `CatalogItemInfo` dataclass SHALL contain `id`, `sku`, `name`, `item_type`, `url`, `image_url`. This map is consumed by `ContextAssembler` to resolve promotion SKUs to product indices.

#### Scenario: Build SKU map from active items

- **WHEN** `build_sku_map()` is called with a list of 2 catalog items with SKUs "BOOK-001" and "EVENT-001"
- **THEN** the result SHALL be a dict with keys "BOOK-001" and "EVENT-001"
- **AND** each value SHALL be a `CatalogItemInfo` with the correct fields

#### Scenario: Empty list returns empty map

- **WHEN** `build_sku_map()` is called with an empty list
- **THEN** the result SHALL be an empty dict
