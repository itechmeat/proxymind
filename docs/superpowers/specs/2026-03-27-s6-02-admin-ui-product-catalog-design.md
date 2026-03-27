# S6-02: Admin UI — Product Catalog

## Overview

Add a product catalog management interface to the Admin UI. The admin (agent owner) can create, edit, delete, and filter catalog items, and see which knowledge sources are linked to each product. Source-to-catalog linking is performed from the Sources tab, while the Catalog tab provides a read-only view of linked sources per product.

**Story reference:** `docs/plan.md` S6-02
**Depends on:** S6-01 (Commerce backend — catalog + recommendations), S5-03 (Admin UI — knowledge management)
**Parallel pair:** S7-02 (Observability) — frontend vs infra, zero file overlap

## Terminology

- **Admin** — the agent owner/operator. The sole user of the Admin UI. Has full CRUD access to catalog, sources, snapshots, and twin settings.
- **Visitor** — an external person who interacts with the twin via the chat interface. Has no access to the Admin UI.

All operations described in this spec are admin-only.

## Design Decisions

### Q1: Navigation — separate tab or nested in Sources?

**Decision: Separate "Catalog" tab.**

Rationale: The product catalog is a distinct domain (commerce), not a subfunction of knowledge sources. Three tabs (Sources, Snapshots, Catalog) is a natural split: content, versioning, commerce. Future phases (S10-05: Owner distribution settings) will add more admin sections, so tab-based navigation is the right pattern to scale.

### Q2: Source ↔ catalog item linking — where?

**Decision: Both places, with clear separation of concerns.**

- **From Catalog tab** — read-only list of linked sources on the catalog item detail view (inside the edit dialog). No mutation controls.
- **From Sources tab** — dropdown to select/change/remove a catalog item link. Available during file upload and via inline editing in the source list.

Rationale: The backend models the relationship as `source.catalog_item_id` (FK on Source, not on CatalogItem). Mutation through Source is the natural direction. The Catalog tab provides overview without duplicating the edit path.

### Q3: Form fields — flat or collapsible?

**Decision: All 8 fields in a single flat form.**

Fields: `sku`, `name`, `description`, `item_type`, `url`, `image_url`, `valid_from`, `valid_until`.

Rationale: 8 fields is a comfortable amount for a dialog. Collapsing would hide commercially important fields (`valid_from/valid_until`, `image_url`). KISS.

### Q4: Catalog list layout — table or cards?

**Decision: Table.**

Rationale: Consistent with the SourceList table pattern already used in the Sources tab. Dense, scannable, works well for 10–50 items.

### Q5: Create/edit form — modal dialog or separate page?

**Decision: Modal dialog.**

Rationale: 8 fields fit comfortably in a dialog. Consistent with existing patterns (ProfileEditModal, AlertDialog). No new routes needed. Admin stays in the context of the list.

### Q6: Deletion — approach?

**Decision: Soft delete with AlertDialog confirmation.**

The backend already implements soft delete (`deleted_at` + `is_active=false`). Soft delete does NOT null out `catalog_item_id` on linked sources — the FK `ondelete=SET NULL` only triggers on physical row deletion, which is not part of the soft delete flow. Sources retain their `catalog_item_id` reference, but the catalog item becomes inactive and is excluded from citation enrichment and recommendations by the dialogue circuit. The confirmation dialog MUST warn the admin that the product will be deactivated and will no longer appear in citations or recommendations.

### Q7: Filtering — scope?

**Decision: Dropdown filter by `item_type` only.**

No text search, no "show inactive" toggle. A typical digital twin catalog has 5–30 items. A type filter is useful at 10+ items and cheap to implement. The backend already supports `item_type` filtering. Search is YAGNI.

### Q8: Implementation approach — state management?

**Decision: Monolithic `useCatalog` hook.**

Follows the existing pattern: `useSources.ts`, `useSnapshots.ts`. One tab = one hook. No Context, no separate UI-state hook. Consistent, minimal, sufficient.

## Component Architecture

### New files

```
frontend/src/
├── pages/AdminPage/
│   └── CatalogTab.tsx              # Tab page: toolbar + list + dialog
├── components/
│   ├── CatalogList/
│   │   ├── CatalogList.tsx         # Table component (mirrors SourceList)
│   │   └── index.ts                # Re-export
│   └── CatalogFormDialog/
│       ├── CatalogFormDialog.tsx   # Create/edit modal (8 fields + linked sources)
│       └── index.ts                # Re-export
├── hooks/
│   └── useCatalog.ts               # State + CRUD operations
```

### Modified files

| File | Change |
|------|--------|
| `App.tsx` | Add route `/admin/catalog` → `CatalogTab` |
| `AdminPage.tsx` | Add third tab "Catalog" to `TabsList` |
| `admin-api.ts` | Add 6 catalog API functions + `updateSource()` |
| `types/admin.ts` | Add catalog types |
| `locales/en/admin.ts` | Add `catalog.*` section |
| `SourcesTab.tsx` | Add optional "Link to product" dropdown on upload |
| `SourceList.tsx` | Add "Product" column + inline link/unlink control |
| `useSources.ts` | Fetch catalog items for dropdown options |

### Not created

- No separate routes for catalog item detail/edit (dialog instead)
- No Context providers or reducers
- No separate UI-state hooks

## TypeScript Types

```typescript
// --- types/admin.ts additions ---

export type CatalogItemType = "book" | "course" | "event" | "merch" | "other";

export interface CatalogItem {
  id: string;
  sku: string;
  name: string;
  description: string | null;
  item_type: CatalogItemType;
  url: string | null;
  image_url: string | null;
  is_active: boolean;
  valid_from: string | null;   // ISO datetime
  valid_until: string | null;  // ISO datetime
  created_at: string;
  updated_at: string;
  linked_sources_count: number;
}

export interface CatalogItemDetail extends CatalogItem {
  linked_sources: LinkedSource[];
}

export interface LinkedSource {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
}

export interface CatalogItemCreate {
  sku: string;
  name: string;
  description?: string | null;
  item_type: CatalogItemType;
  url?: string | null;
  image_url?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
}

export interface CatalogItemUpdate {
  sku?: string;
  name?: string;
  description?: string | null;
  item_type?: CatalogItemType;
  url?: string | null;
  image_url?: string | null;
  is_active?: boolean;
  valid_from?: string | null;
  valid_until?: string | null;
}

export interface CatalogItemListResponse {
  items: CatalogItem[];
  total: number;
}

export interface SourceUpdateRequest {
  catalog_item_id: string | null;
}
```

## API Client

New functions in `admin-api.ts`:

| Function | Method | Endpoint | Notes |
|----------|--------|----------|-------|
| `getCatalogItems(type?)` | GET | `/api/admin/catalog?item_type=X` | Optional type filter |
| `getCatalogItem(id)` | GET | `/api/admin/catalog/:id` | Returns detail with linked sources |
| `createCatalogItem(data)` | POST | `/api/admin/catalog` | Returns created item |
| `updateCatalogItem(id, data)` | PATCH | `/api/admin/catalog/:id` | Partial update |
| `deleteCatalogItem(id)` | DELETE | `/api/admin/catalog/:id` | Soft delete |
| `updateSource(id, data)` | PATCH | `/api/admin/sources/:id` | Link/unlink catalog item |

All functions follow the existing pattern: `fetch()` + `buildApiUrl()` + `parseJsonResponse()`.

## Hook: `useCatalog`

Follows `useSources.ts` / `useSnapshots.ts` pattern.

### State

| Field | Type | Purpose |
|-------|------|---------|
| `items` | `CatalogItem[]` | Current filtered list |
| `isLoading` | `boolean` | Initial load indicator |
| `filterType` | `CatalogItemType \| null` | Active type filter (null = all) |
| `editingItem` | `CatalogItem \| null` | null = create mode, object = edit mode |
| `isDialogOpen` | `boolean` | Form dialog visibility |
| `isSaving` | `boolean` | Save-in-progress indicator |
| `deletingItemId` | `string \| null` | Item being deleted (for UI feedback) |

### Actions

| Action | Behavior |
|--------|----------|
| `loadItems()` | Fetch items with current `filterType`, update `items` |
| `saveItem(data)` | Create or update depending on `editingItem`, then refresh + close dialog |
| `removeItem(id)` | Soft delete, then refresh list |
| `openCreate()` | Set `editingItem=null`, `isDialogOpen=true` |
| `openEdit(item)` | Set `editingItem=item`, `isDialogOpen=true` |
| `closeDialog()` | Set `isDialogOpen=false`, `editingItem=null` |
| `setFilterType(type)` | Update filter, triggers reload |

### Effects

- `useEffect` on mount: call `loadItems()`
- `useEffect` on `filterType` change: call `loadItems()`

## UI Components

### CatalogTab

Top toolbar:
- **"+ Add Product"** button (calls `openCreate()`)
- **Type filter** dropdown: All / Book / Course / Event / Merch / Other (calls `setFilterType()`)

Below toolbar:
- `CatalogList` component
- `CatalogFormDialog` component (controlled by `isDialogOpen`)

### CatalogList

Desktop table columns:

| Column | Content |
|--------|---------|
| Name | Item name, font-weight 500 |
| SKU | Monospace, muted color |
| Type | Badge with type-specific color |
| Sources | "N linked" count |
| Actions | Edit link + Delete button |

Mobile: card layout (same pattern as SourceList mobile view).

Empty state: "No products yet. Add a product to start building the catalog."

Type badge colors:
- Book → blue
- Course → amber
- Event → purple
- Merch → emerald
- Other → stone/gray

### CatalogFormDialog

Radix Dialog (not AlertDialog — AlertDialog is for confirmations only).

**Create mode:** empty form, title "Add product", save button "Create".
**Edit mode:** pre-filled form, title "Edit product", save button "Save changes".

Form fields (all in one flat layout):

| Field | Input type | Required | Validation |
|-------|-----------|----------|------------|
| SKU | text input | Yes | Non-empty, max 64 chars |
| Name | text input | Yes | Non-empty, max 255 chars |
| Description | textarea | No | Max 2000 chars |
| Type | select dropdown | Yes | One of enum values |
| URL | text input | No | Valid URL format if provided |
| Image URL | text input | No | Valid URL format if provided |
| Valid from | date input | No | — |
| Valid until | date input | No | Must be ≥ valid_from if both set |

**Linked sources section (edit mode only):**
Below the form fields, a read-only list showing sources linked to this catalog item. Each entry shows source title + type badge + status badge. If no sources are linked: "No sources linked to this product."

This section is populated by fetching `getCatalogItem(id)` when the dialog opens in edit mode (returns `CatalogItemDetail` with `linked_sources`).

### Delete Confirmation

AlertDialog (existing pattern from source deletion):
- Title: "Delete product {name}?"
- Description: "This product will be deactivated and will no longer appear in citations or recommendations. Linked sources will retain their reference, but it will have no effect until the product is reactivated."
- Actions: Cancel / Delete

## Source ↔ Catalog Linking in Sources Tab

### Upload flow

A "Link to product" dropdown is placed **outside the DropZone component**, as a sibling control below or beside it. The DropZone is a single clickable/droppable area; embedding interactive controls inside it would create event conflicts. The dropdown is a standalone `<select>` element:
- Options populated from `getCatalogItems()` (fetched once in `useSources` init)
- Shows `name` + `sku` for each option
- Selection sets `catalog_item_id` in `SourceUploadMetadata`
- Default: no selection (unlinked)
- **Batch semantics:** the selected product applies to **all files** in a single batch upload. For per-file linking, the admin uploads separately or uses the inline dropdown in the source list after upload

### Source list

`SourceList` table gets a new column "Product":
- Linked: inline `<select>` dropdown showing the currently linked product, changeable
- Unlinked: dropdown defaulting to "Select a product..."
- Selection calls `updateSource(sourceId, { catalog_item_id })` then refreshes

### Catalog items for dropdown

`useSources` fetches the catalog items list on init to populate dropdown options. This is a flat array of `{id, name, sku}` — no full model needed. If the catalog is empty, the dropdown shows "No products available" with a hint to visit the Catalog tab.

### Stale reference handling

If a source has a `catalog_item_id` that is not present in the fetched active catalog items list (e.g., the product was soft-deleted), the dropdown MUST still show the current value as a fallback option (e.g., "(unknown product)") so the admin can see the stale link and unlink it. This does not require backend changes — it is handled entirely in the frontend rendering logic.

## Internationalization

New `catalog` section in `locales/en/admin.ts`:

```typescript
catalog: {
  tab: "Catalog",
  addProduct: "+ Add Product",
  filterAll: "All types",
  loading: "Loading catalog...",
  loadFailed: "Failed to load catalog",
  emptyState: "No products yet. Add a product to start building the catalog.",
  table: {
    name: "Name",
    sku: "SKU",
    type: "Type",
    sources: "Sources",
    actions: "Actions",
    linkedCount: "{{count}} linked",
    noLinks: "—",
  },
  type: {
    book: "Book",
    course: "Course",
    event: "Event",
    merch: "Merch",
    other: "Other",
  },
  form: {
    createTitle: "Add product",
    editTitle: "Edit product",
    sku: "SKU",
    skuPlaceholder: "e.g. BOOK-001",
    name: "Name",
    namePlaceholder: "Product name",
    description: "Description",
    descriptionPlaceholder: "Optional product description",
    itemType: "Type",
    url: "URL",
    urlPlaceholder: "https://store.example.com/product",
    imageUrl: "Image URL",
    imageUrlPlaceholder: "https://example.com/image.jpg",
    validFrom: "Valid from",
    validUntil: "Valid until",
    linkedSources: "Linked sources",
    noLinkedSources: "No sources linked to this product.",
    create: "Create",
    save: "Save changes",
    cancel: "Cancel",
  },
  toast: {
    created: "Product \"{{name}}\" created",
    updated: "Product \"{{name}}\" updated",
    deleted: "Product \"{{name}}\" deleted",
    createFailed: "Failed to create product",
    updateFailed: "Failed to update product",
    deleteFailed: "Failed to delete product",
    skuConflict: "A product with this SKU already exists",
  },
  delete: {
    title: "Delete product {{name}}?",
    description: "This product will be deactivated and will no longer appear in citations or recommendations. Linked sources will retain their reference, but it will have no effect until the product is reactivated.",
    action: "Delete product",
  },
  sourceLink: {
    label: "Link to product",
    placeholder: "Select a product...",
    noProducts: "No products available",
    noProductsHint: "Create products in the Catalog tab first.",
    unlink: "Unlink",
    unknownProduct: "unknown product",
  },
}
```

## Error Handling

| Scenario | HTTP Status | UI Behavior |
|----------|-------------|-------------|
| SKU conflict on create/update | 409 | Toast: "A product with this SKU already exists" |
| Item not found | 404 | Toast: "Product not found", refresh list |
| Network error | — | Toast with generic error message |
| Validation error | 422 | Highlight invalid fields, show inline messages |
| Delete linked item | 200 (soft delete) | AlertDialog warns that product will be deactivated and excluded from citations/recommendations |

After every mutation (create, update, delete): refresh the catalog list. Same pattern as `useSources`.

## Testing Strategy

**Deploy tests (CI):**
- Component rendering: CatalogList with items, empty state, filter
- CatalogFormDialog: create mode, edit mode, validation, linked sources display
- useCatalog hook: CRUD operations with mocked API responses
- Source linking dropdown: render with/without catalog items

**Not in scope:**
- E2E browser tests (no Playwright/Cypress in the project yet)
- Backend tests (already covered by S6-01)

## Out of Scope

- Full-text search in catalog
- Image upload for products (image_url is a plain text field)
- Drag-and-drop reordering
- Bulk operations (mass delete, mass edit)
- "Show inactive" toggle
- Catalog item detail page (separate route)
- Analytics or sales tracking
