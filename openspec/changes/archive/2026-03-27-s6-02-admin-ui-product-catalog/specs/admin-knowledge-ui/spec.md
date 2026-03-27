## Purpose

Frontend admin interface for knowledge management — source upload, source list with status tracking, snapshot lifecycle management, draft testing. Includes admin routing, layout, and access control via environment flag. Introduced by S5-03. Modified by S6-02 to add source-catalog linking controls.

## ADDED Requirements

### Requirement: Catalog options API contract

`useSources` MUST load catalog options from `GET /api/admin/catalog`. The response SHALL follow the paginated catalog contract from `catalog-crud`: an object with `items` (array) and `total` (integer). Each object in `items` SHALL include at minimum `id` (string UUID), `name` (string), `sku` (string), and `is_active` (boolean). `useSources` SHALL consume only active items (`is_active=true`) for the Product dropdowns, SHALL use `id` in `PATCH /api/admin/sources/:id` payloads, and SHALL display `name` plus `sku` in both the inline Product dropdown and the upload Product dropdown. When `items` is empty, the dropdown SHALL render the disabled option from translation key `admin.sourceLink.noProducts`.

Example response:

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "AI in Practice",
      "sku": "BOOK-001",
      "is_active": true
    }
  ],
  "total": 1
}
```

#### Scenario: `GET /api/admin/catalog` returns active catalog options

- **WHEN** `useSources` initializes and `GET /api/admin/catalog` returns one active item
- **THEN** the frontend SHALL read the option from `response.items[0]`
- **AND** the Product dropdown SHALL display `AI in Practice (BOOK-001)`
- **AND** `PATCH /api/admin/sources/:id` SHALL use the item's `id` value in the request body

#### Scenario: Empty catalog response shows disabled no-products option

- **WHEN** `GET /api/admin/catalog` returns `{ "items": [], "total": 0 }`
- **THEN** the Product dropdown SHALL show the disabled option from translation key `admin.sourceLink.noProducts`
- **AND** the default placeholder from translation key `admin.sourceLink.placeholder` SHALL remain available as the empty value

---

### Requirement: Source-catalog linking column

The source list table on the Sources tab MUST include a "Product" column with an inline select dropdown for linking or unlinking a catalog item per source. `useSources` SHALL fetch catalog items during initialization, SHALL re-fetch them when the Sources view regains focus, SHALL support a configurable polling interval (default 60s), and SHALL expose a manual refresh function that the UI can call after a failed fetch. Each dropdown option SHALL display the item's `name` and `sku`. The default option SHALL be "Select a product..." (from translation key `admin.sourceLink.placeholder`). Selecting a catalog item SHALL send `PATCH /api/admin/sources/:id` with `{ "catalog_item_id": "<selected-item-id>" }`. Selecting the default/empty option SHALL send `PATCH /api/admin/sources/:id` with `{ "catalog_item_id": null }` to unlink. After a successful link/unlink operation, the source list SHALL re-fetch. On mobile card layout, the Product dropdown SHALL appear within each source card.

#### Scenario: Product column renders with inline dropdown

- **WHEN** the source list table renders on desktop
- **THEN** a "Product" column SHALL appear with an inline select dropdown in each row

#### Scenario: Dropdown populated with active catalog items

- **WHEN** the source list renders and 3 active catalog items exist
- **THEN** each source row's Product dropdown SHALL contain 3 options (plus the default placeholder)
- **AND** each option SHALL display the catalog item's name and SKU

#### Scenario: Catalog options refresh when the Sources view regains focus

- **WHEN** the admin returns to the Sources tab or the Sources view regains browser focus
- **THEN** `useSources` SHALL trigger the same `GET /api/admin/catalog` fetch used during initialization
- **AND** the refreshed options SHALL populate both the inline Product dropdown and the upload Product dropdown

#### Scenario: Catalog options refresh on polling interval

- **WHEN** the Sources view remains open for longer than the configured catalog polling interval
- **THEN** `useSources` SHALL re-fetch `GET /api/admin/catalog`
- **AND** the default polling interval SHALL be 60 seconds unless explicitly overridden

#### Scenario: Manual retry re-fetches catalog options

- **WHEN** the catalog options fetch previously failed and the admin activates the retry control
- **THEN** the UI SHALL call the manual refresh function exposed by `useSources`
- **AND** that refresh SHALL trigger `GET /api/admin/catalog` again

#### Scenario: Linking a source to a product

- **WHEN** the user selects "AI in Practice (BOOK-001)" from the Product dropdown on a source row
- **THEN** a `PATCH /api/admin/sources/:id` request SHALL be sent with `{ "catalog_item_id": "<item-uuid>" }`
- **AND** on success, the source list SHALL re-fetch

#### Scenario: Unlinking a source from a product

- **WHEN** a source is currently linked to a product and the user selects the default "Select a product..." option
- **THEN** a `PATCH /api/admin/sources/:id` request SHALL be sent with `{ "catalog_item_id": null }`
- **AND** on success, the source list SHALL re-fetch

#### Scenario: Empty catalog shows disabled placeholder

- **WHEN** the catalog has zero active items
- **THEN** the Product dropdown SHALL show the disabled option from translation key `admin.sourceLink.noProducts`
- **AND** the dropdown SHALL not be selectable

#### Scenario: Catalog fetch failure shows retryable disabled state

- **WHEN** `GET /api/admin/catalog` fails during `useSources` initialization
- **THEN** the Product dropdown SHALL show a disabled "Failed to load products" option
- **AND** the default placeholder from translation key `admin.sourceLink.placeholder` SHALL remain defined as the empty value
- **AND** a retry mechanism SHALL be available in the Sources UI

#### Scenario: PATCH failure preserves previous selection

- **WHEN** `PATCH /api/admin/sources/:id` fails because of a network, validation, or permission error
- **THEN** an error message SHALL be shown to the user
- **AND** the Product dropdown SHALL revert to its previous value
- **AND** the source list SHALL NOT re-fetch

#### Scenario: Product dropdown on mobile cards

- **WHEN** the source list renders as cards on a mobile viewport
- **THEN** each source card SHALL include the Product linking dropdown

---

### Requirement: Stale reference handling

If a source has a `catalog_item_id` that is not present in the fetched list of active catalog items (e.g., the linked product was soft-deleted), `components/SourceList/SourceList.tsx` MUST still display the current value as a fallback option with the label "(unknown product)" (from translation key `admin.sourceLink.unknownProduct`). This allows the admin to see the stale link in a clear read-only/current-value state and unlink it by selecting the default option. The fallback option SHALL only appear in the dropdown for that specific source — it SHALL NOT pollute other sources' dropdowns. `hooks/useSources.ts` SHALL continue to provide the refreshed active options so that, when the dropdown is opened, the admin can clear or replace the stale reference without losing access to the valid active list.

#### Scenario: Stale reference shows unknown product fallback

- **WHEN** a source has `catalog_item_id = "abc-123"` but "abc-123" is not in the active catalog items list
- **THEN** the Product dropdown for that source SHALL show "(unknown product)" as the selected value

#### Scenario: Admin can unlink stale reference

- **WHEN** the Product dropdown shows "(unknown product)" for a source with a stale reference
- **AND** the user selects the default "Select a product..." option
- **THEN** a `PATCH /api/admin/sources/:id` request SHALL be sent with `{ "catalog_item_id": null }`
- **AND** on success, the source list SHALL re-fetch and the "(unknown product)" option SHALL disappear

#### Scenario: Fallback option scoped to affected source only

- **WHEN** source A has a stale `catalog_item_id` and source B has a valid `catalog_item_id`
- **THEN** the "(unknown product)" fallback option SHALL appear only in source A's dropdown
- **AND** source B's dropdown SHALL show the correct product name without any fallback entries

#### Scenario: Admin can replace stale reference with a refreshed option

- **WHEN** source A has a stale `catalog_item_id`
- **AND** `useSources` has refreshed the active catalog options
- **THEN** opening the Product dropdown SHALL show the stale fallback plus the current active options
- **AND** the admin SHALL be able to select a new active product to replace the stale reference

---

### Requirement: Product dropdown accessibility

The inline Product dropdown and the upload Product dropdown MUST support keyboard and screen-reader usage. The control SHALL be reachable via Tab, SHALL open with native select/combobox keyboard interaction (including Enter/Space), SHALL support Arrow-key option navigation, and SHALL expose an accessible name via either a visible `<label>` or `aria-label`. Screen readers SHALL be able to announce the current selection and the available options, including the placeholder from translation key `admin.sourceLink.placeholder` and the empty-state option from `admin.sourceLink.noProducts`. Table rows and mobile source cards SHALL preserve a logical focus order so the Product dropdown can be reached without skipping the row/card actions.

#### Scenario: Keyboard user focuses and operates the Product dropdown

- **WHEN** a keyboard-only user Tabs through the Sources table
- **THEN** the inline Product dropdown SHALL receive focus
- **AND** the user SHALL be able to open it with Enter or Space and navigate options with the Arrow keys

#### Scenario: Screen reader announces desktop Product dropdown

- **WHEN** a screen reader focuses the Product dropdown in a source row
- **THEN** it SHALL announce the Product label, the source-specific current selection, and the available options

#### Scenario: Mobile source cards preserve Product dropdown focus order

- **WHEN** the source list renders as mobile cards
- **THEN** each card SHALL include the Product dropdown in the normal Tab order
- **AND** the card's Product label and current selection SHALL remain exposed to assistive technology

---

### Requirement: Upload product linking

The Sources tab upload area MUST include a "Link to product" dropdown placed **outside** the DropZone component, as a sibling control. The dropdown SHALL NOT be nested inside the DropZone to avoid event conflicts with drag-and-drop interactions. The dropdown SHALL be populated with active catalog items (same data source as the source list Product column). The default selection SHALL be empty (no product linked). When a product is selected and files are uploaded, the selected `catalog_item_id` SHALL be included in the upload metadata for each file in the batch. Batch semantics: the selected product applies to all files in a single drop/pick operation. For per-file linking, the admin uses the inline dropdown in the source list after upload. The dropdown label SHALL use translation key `admin.sourceLink.label`. If the catalog is empty, the dropdown SHALL show "No products available" with a hint to visit the Catalog tab (from translation keys `admin.sourceLink.noProducts` and `admin.sourceLink.noProductsHint`).

#### Scenario: Link to product dropdown renders outside DropZone

- **WHEN** the Sources tab renders
- **THEN** a "Link to product" dropdown SHALL appear as a sibling element to the DropZone
- **AND** it SHALL NOT be nested inside the DropZone's clickable/droppable area

#### Scenario: Upload with product link applies to all files in batch

- **WHEN** the user selects "AI in Practice (BOOK-001)" from the upload product dropdown
- **AND** drops 3 files onto the DropZone
- **THEN** all 3 `POST /api/admin/sources` requests SHALL include `catalog_item_id` matching the selected product

#### Scenario: Upload without product link sends no catalog_item_id

- **WHEN** no product is selected in the upload dropdown (default state)
- **AND** the user drops files onto the DropZone
- **THEN** the upload requests SHALL NOT include a `catalog_item_id` field

#### Scenario: Empty catalog shows hint to visit Catalog tab

- **WHEN** the catalog has zero active items
- **THEN** the upload product dropdown SHALL show "No products available" as a disabled option
- **AND** a hint text SHALL display directing the admin to create products in the Catalog tab
