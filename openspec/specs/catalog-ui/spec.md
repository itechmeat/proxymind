## Purpose

Admin UI tab for product catalog management — CRUD table with type filter, modal form for create/edit, soft delete with confirmation, read-only linked sources display in edit mode. All user-facing strings use i18next translation keys. Introduced by S6-02.

## Requirements

### Requirement: Catalog tab navigation

The Admin UI MUST include a "Catalog" tab as the third tab in the admin top-level navigation, after "Sources" and "Snapshots". The tab SHALL link to `/admin/catalog`. On mobile, tabs SHALL span full width (33.3% each for three tabs). The Catalog tab label MUST use the i18next translation key `admin.catalog.tab`.

#### Scenario: Catalog tab renders as third tab

- **WHEN** the admin layout renders
- **THEN** the tab bar SHALL display three tabs: "Sources", "Snapshots", "Catalog" in that order
- **AND** the "Catalog" tab SHALL link to `/admin/catalog`

#### Scenario: Catalog tab activates on navigation

- **WHEN** the user clicks the "Catalog" tab
- **THEN** the browser SHALL navigate to `/admin/catalog`
- **AND** the Catalog tab SHALL have active styling
- **AND** the "Sources" and "Snapshots" tabs SHALL have inactive styling

#### Scenario: Mobile responsive three-tab layout

- **WHEN** the viewport width is below the mobile breakpoint
- **THEN** the three tabs SHALL each occupy approximately 33.3% of the available width

### Requirement: Catalog list table

The Catalog tab MUST display catalog items in a table on desktop with the following columns: Name (item name, font-weight 500), SKU (monospace, muted color), Type (badge with type-specific color), Sources (count of linked sources, e.g. "N linked"), and Actions (edit button + delete button). On mobile, the list MUST render as a card layout with each card showing name, SKU, type badge, linked sources count, and action buttons. Items SHALL be ordered by `created_at` descending (newest first). Type badge colors SHALL be: book = blue, course = amber, event = purple, merch = emerald, other = stone/gray.

#### Scenario: Table renders on desktop with correct columns

- **WHEN** the Catalog tab renders on a desktop viewport with 3 catalog items
- **THEN** a table SHALL display with columns: Name, SKU, Type, Sources, Actions
- **AND** each row SHALL show the corresponding item data

#### Scenario: Card layout renders on mobile

- **WHEN** the Catalog tab renders on a mobile viewport
- **THEN** items SHALL display as cards instead of a table
- **AND** each card SHALL show name, SKU, type badge, linked sources count, and action buttons

#### Scenario: Type badge colors match item type

- **WHEN** an item has `item_type = "book"`
- **THEN** its type badge SHALL be blue

- **WHEN** an item has `item_type = "course"`
- **THEN** its type badge SHALL be amber

- **WHEN** an item has `item_type = "event"`
- **THEN** its type badge SHALL be purple

- **WHEN** an item has `item_type = "merch"`
- **THEN** its type badge SHALL be emerald

- **WHEN** an item has `item_type = "other"`
- **THEN** its type badge SHALL be stone/gray

#### Scenario: Items sorted by creation date descending

- **WHEN** the catalog list renders with items created at different times
- **THEN** the newest item SHALL appear first in the list

### Requirement: Type filter

The Catalog tab MUST provide a dropdown filter to narrow the list by `item_type`. The dropdown SHALL offer options: "All types" (default, shows all items), "Book", "Course", "Event", "Merch", "Other". Selecting a type SHALL call `GET /api/admin/catalog?item_type={type}` to fetch only matching items. Selecting "All types" SHALL fetch without the `item_type` parameter. The filter selection SHALL be reflected immediately in the displayed list.

#### Scenario: Default filter shows all items

- **WHEN** the Catalog tab renders for the first time
- **THEN** the type filter dropdown SHALL display "All types"
- **AND** the list SHALL show all active catalog items regardless of type

#### Scenario: Filtering by book type

- **WHEN** the user selects "Book" from the type filter dropdown
- **THEN** a `GET /api/admin/catalog?item_type=book` request SHALL be sent
- **AND** only items with `item_type = "book"` SHALL appear in the list

#### Scenario: Clearing filter returns to all items

- **WHEN** the user selects "All types" after having a type filter active
- **THEN** a `GET /api/admin/catalog` request SHALL be sent without the `item_type` parameter
- **AND** all active catalog items SHALL appear in the list

### Requirement: Create product

The Catalog tab MUST provide a "+ Add Product" button in the toolbar. Clicking it SHALL open a Radix Dialog (not AlertDialog) in create mode with the title "Add product" (from translation key `admin.catalog.form.createTitle`). The dialog SHALL contain 8 form fields: `sku` (text input, required, max 64 chars), `name` (text input, required, max 255 chars), `description` (textarea, optional, max 2000 chars), `item_type` (select dropdown, required, one of book/course/event/merch/other), `url` (text input, optional, valid URL format if provided), `image_url` (text input, optional, valid URL format if provided), `valid_from` (date input, optional), `valid_until` (date input, optional, must be >= `valid_from` if both set). The save button SHALL read "Create" (from translation key `admin.catalog.form.create`). Submitting SHALL send `POST /api/admin/catalog` with the form data. On success, the catalog list SHALL re-fetch and a success toast SHALL display. The dialog SHALL close on successful save.

#### Scenario: Add product button opens create dialog

- **WHEN** the user clicks "+ Add Product"
- **THEN** a dialog SHALL open with title "Add product" and an empty form
- **AND** the save button SHALL read "Create"

#### Scenario: Successful product creation

- **WHEN** the user fills in `sku: "BOOK-001"`, `name: "AI in Practice"`, `item_type: "book"` and clicks "Create"
- **THEN** a `POST /api/admin/catalog` request SHALL be sent with the form data
- **AND** on success, the dialog SHALL close
- **AND** the catalog list SHALL re-fetch
- **AND** a success toast SHALL display

#### Scenario: Required field validation

- **WHEN** the user clicks "Create" with the `sku` field empty
- **THEN** the form SHALL NOT submit
- **AND** the `sku` field SHALL show a validation error

#### Scenario: Date range validation

- **WHEN** `valid_from` is set to "2026-06-01" and `valid_until` is set to "2026-05-01"
- **THEN** the form SHALL show a validation error on `valid_until` indicating it must be on or after `valid_from`

### Requirement: Edit product

Clicking the edit button on a catalog item row MUST open the same dialog in edit mode. The dialog title SHALL be "Edit product" (from translation key `admin.catalog.form.editTitle`). All form fields SHALL be pre-filled with the item's current values. The save button SHALL read "Save changes" (from translation key `admin.catalog.form.save`). Submitting SHALL send `PATCH /api/admin/catalog/:id` with only changed fields. On success, the catalog list SHALL re-fetch and a success toast SHALL display.

In edit mode, a read-only "Linked sources" section MUST appear below the form fields. This section SHALL be populated by fetching `GET /api/admin/catalog/:id` (which returns `CatalogItemDetail` with `linked_sources`). Each linked source SHALL display its title, source type badge, and status badge. If no sources are linked, the section SHALL show the message from translation key `admin.catalog.form.noLinkedSources`. The fetch MUST use the active guard pattern for safe async cleanup (see "Linked sources in edit dialog" requirement).

#### Scenario: Edit button opens pre-filled dialog

- **WHEN** the user clicks the edit button on a catalog item with `sku: "BOOK-001"`, `name: "AI in Practice"`
- **THEN** a dialog SHALL open with title "Edit product"
- **AND** the `sku` field SHALL contain "BOOK-001"
- **AND** the `name` field SHALL contain "AI in Practice"
- **AND** the save button SHALL read "Save changes"

#### Scenario: Successful product update

- **WHEN** the user changes the `name` field to "AI in Practice 2nd Ed" and clicks "Save changes"
- **THEN** a `PATCH /api/admin/catalog/:id` request SHALL be sent with `{"name": "AI in Practice 2nd Ed"}`
- **AND** on success, the dialog SHALL close and the catalog list SHALL re-fetch

#### Scenario: Linked sources displayed in edit mode

- **WHEN** the edit dialog opens for a catalog item that has 3 linked sources
- **THEN** the "Linked sources" section SHALL display 3 entries with title, type badge, and status badge

#### Scenario: No linked sources message

- **WHEN** the edit dialog opens for a catalog item that has zero linked sources
- **THEN** the "Linked sources" section SHALL display "No sources linked to this product."

### Requirement: Delete product

Each catalog item row MUST have a delete button. Clicking the delete button MUST open an AlertDialog with the title from translation key `admin.catalog.delete.title` (interpolated with the product name) and the description from translation key `admin.catalog.delete.description`, which warns that the product will be deactivated and will no longer appear in citations or recommendations. The confirm button SHALL read "Delete product". Confirming SHALL send `DELETE /api/admin/catalog/:id`. On success, the catalog list SHALL re-fetch and a success toast SHALL display. Canceling SHALL close the dialog with no side effects.

#### Scenario: Delete button opens confirmation dialog

- **WHEN** the user clicks the delete button on a product named "AI in Practice"
- **THEN** an AlertDialog SHALL open with the title "Delete product AI in Practice?"
- **AND** the description SHALL warn about deactivation and exclusion from citations/recommendations

#### Scenario: Confirm delete sends request and refreshes list

- **WHEN** the user confirms the delete in the AlertDialog
- **THEN** a `DELETE /api/admin/catalog/:id` request SHALL be sent
- **AND** on success, the catalog list SHALL re-fetch
- **AND** a success toast SHALL display

#### Scenario: Cancel delete has no side effects

- **WHEN** the user cancels the delete in the AlertDialog
- **THEN** the dialog SHALL close
- **AND** no delete request SHALL be sent

### Requirement: SKU conflict handling

When a create or update request returns HTTP 409 (Conflict), the UI MUST show a specific toast with the message from translation key `admin.catalog.toast.skuConflict` ("A product with this SKU already exists"). The dialog SHALL remain open so the admin can correct the SKU. The catalog list SHALL be re-fetched to ensure consistency.

#### Scenario: 409 on create shows SKU conflict toast

- **WHEN** the user submits a create form and the backend returns 409
- **THEN** a toast SHALL display "A product with this SKU already exists"
- **AND** the dialog SHALL remain open with the form data intact
- **AND** the catalog list SHALL be re-fetched

#### Scenario: 409 on update shows SKU conflict toast

- **WHEN** the user submits an edit form changing the SKU and the backend returns 409
- **THEN** a toast SHALL display "A product with this SKU already exists"
- **AND** the dialog SHALL remain open with the form data intact
- **AND** the catalog list SHALL be re-fetched

### Requirement: Empty state

When the catalog list has no items (either because no products exist or the active filter returns zero results), the table area MUST display a helpful empty state message. When no products exist at all (no filter active), the message SHALL use translation key `admin.catalog.emptyState` ("No products yet. Add a product to start building the catalog."). When a type filter is active but returns zero results, the empty state MUST indicate that no products match the selected type.

#### Scenario: Empty catalog with no filter

- **WHEN** the Catalog tab renders and zero catalog items exist
- **THEN** the table area SHALL display "No products yet. Add a product to start building the catalog."

#### Scenario: Empty result with active type filter

- **WHEN** the user selects "Event" from the type filter and zero event items exist
- **THEN** the table area SHALL display a message indicating no products match the selected type

### Requirement: Linked sources in edit dialog

When the edit dialog opens, it MUST fetch the catalog item detail (including `linked_sources`) from `GET /api/admin/catalog/:id`. The async fetch MUST use the active guard pattern to prevent stale state updates: on effect initialization, set `let active = true`; on cleanup, set `active = false`; before applying the fetched result to state, check that `active` is still `true`. This prevents race conditions when the user quickly opens and closes dialogs or switches between items.

#### Scenario: Active guard prevents stale update

- **WHEN** the user opens the edit dialog for item A, then immediately closes it and opens the dialog for item B
- **THEN** the fetch result for item A SHALL NOT be applied to the dialog state
- **AND** only the fetch result for item B SHALL populate the linked sources section

#### Scenario: Successful fetch populates linked sources

- **WHEN** the edit dialog opens and the fetch completes while the dialog is still open for the same item
- **THEN** the linked sources section SHALL display the fetched sources

#### Scenario: Cleanup on dialog close

- **WHEN** the edit dialog is closed while a fetch is in progress
- **THEN** the active guard SHALL be set to `false`
- **AND** the pending fetch result SHALL be discarded when it arrives

### Requirement: Internationalization

All user-facing strings in the Catalog tab, CatalogList, CatalogFormDialog, and delete confirmation MUST use i18next translation keys from the `admin.catalog.*` namespace. No hardcoded user-facing strings SHALL appear in component render output. Labels, placeholders, button text, toast messages, empty state messages, and validation messages MUST all be sourced from translation keys.

#### Scenario: All visible text uses translation keys

- **WHEN** the Catalog tab and its child components render
- **THEN** every user-facing string (tab label, button labels, column headers, form labels, placeholders, toast messages, empty state text, dialog titles, confirmation messages) SHALL be rendered via `t()` calls using `admin.catalog.*` translation keys

#### Scenario: Translation keys are defined

- **WHEN** the i18n configuration loads
- **THEN** the `admin.catalog` namespace SHALL contain all keys referenced by catalog components including: `tab`, `addProduct`, `filterAll`, `emptyState`, `table.*`, `type.*`, `form.*`, `toast.*`, `delete.*`
- **AND** the `admin.sourceLink` namespace SHALL contain all keys referenced by source-catalog linking controls including: `label`, `placeholder`, `noProducts`, `noProductsHint`, `unlink`, `unknownProduct`
