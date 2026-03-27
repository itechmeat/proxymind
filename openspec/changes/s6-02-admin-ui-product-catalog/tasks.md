## 0. TODO Stub Resolution

No `TODO(S6-02)` stubs found in the codebase (verified via `grep -r "TODO(S6-02)"`). No stub-resolution tasks required.

## 1. Types and API Client

- [x] 1.1 Add `catalog_item_id` field to existing `SourceListItem` interface in `types/admin.ts`
- [x] 1.2 Add catalog TypeScript types (`CatalogItemType`, `CatalogItem`, `CatalogItemDetail`, `LinkedSource`, `CatalogItemCreate`, `CatalogItemUpdate`, `CatalogItemListResponse`, `SourceUpdateRequest`) to `types/admin.ts`
- [x] 1.3 Add catalog API client functions to `admin-api.ts`: `getCatalogItems`, `getCatalogItem`, `createCatalogItem`, `updateCatalogItem`, `deleteCatalogItem`, `updateSource`
- [x] 1.4 Verify types compile: `bun run check`

## 2. Internationalization

- [x] 2.1 Add `catalog` section to `locales/en/admin.ts` (tab label, table headers, form labels, type labels, toast messages, delete confirmation, empty states)
- [x] 2.2 Add `sourceLink` section to `locales/en/admin.ts` as a sibling of `catalog` — keys resolve to `admin.sourceLink.*` (link label, placeholder, no products hint, unlink, unknown product)
- [x] 2.3 Add `translateCatalogItemType` helper to `lib/i18n.ts` with `CatalogItemType` import

## 3. Catalog Hook

- [x] 3.1 Create `hooks/useCatalog.ts` with state (items, isLoading, filterType, editingItem, isDialogOpen, isSaving, deletingItemId) and actions (loadItems, saveItem, removeItem, openCreate, openEdit, closeDialog, setFilterType)
- [x] 3.2 Implement SKU conflict handling (detect 409 via ApiError, show specific toast)
- [x] 3.3 Verify types compile: `bun run check`

## 4. Catalog List Component

- [x] 4.1 Create `components/CatalogList/CatalogList.tsx` — table with Name, SKU, Type badge, Sources count, Actions (Edit + Delete) columns; mobile card layout
- [x] 4.2 Create `components/CatalogList/index.ts` re-export
- [x] 4.3 Implement delete confirmation AlertDialog with correct soft-delete warning text (deactivation, excluded from citations/recommendations)
- [x] 4.4 Implement empty state message

## 5. Catalog Form Dialog

- [x] 5.1 Create `components/CatalogFormDialog/CatalogFormDialog.tsx` — Radix Dialog with 8 form fields, create/edit modes
- [x] 5.2 Create `components/CatalogFormDialog/index.ts` re-export
- [x] 5.3 Implement linked sources read-only section in edit mode with async fetch using active guard pattern (`let active = true` / cleanup)
- [x] 5.4 Implement form validation (sku and name required, valid_until >= valid_from)

## 6. Catalog Tab and Routing

- [x] 6.1 Create `pages/AdminPage/CatalogTab.tsx` — toolbar with "+ Add Product" button and type filter dropdown, CatalogList, CatalogFormDialog
- [x] 6.2 Export `CatalogTab` from `pages/AdminPage/index.ts`
- [x] 6.3 Add "Catalog" tab to `AdminPage.tsx` TabsList
- [x] 6.4 Add `/admin/catalog` route to `App.tsx`

## 7. Source-Catalog Linking in Sources Tab

- [x] 7.1 Add catalog items loading and `linkSourceToCatalog` callback to `useSources.ts`
- [x] 7.2 Add "Product" column with inline select dropdown to `SourceList.tsx` (desktop table and mobile cards)
- [x] 7.3 Implement stale reference handling — show "(unknown product)" fallback option when source.catalog_item_id not in active catalog items
- [x] 7.4 Add "Link to product" dropdown outside DropZone in `SourcesTab.tsx` with batch upload semantics
- [x] 7.5 Update `uploadFiles` in `useSources.ts` to accept optional `catalogItemId` parameter

## 8. Automated Tests

- [x] 8.1 Write component tests for CatalogList: renders table with items, shows empty state, type badges, delete confirmation dialog
- [x] 8.2 Write component tests for CatalogFormDialog: create mode (empty form), edit mode (pre-filled), linked sources display, validation (required fields)
- [x] 8.3 Write hook tests for useCatalog: CRUD operations with mocked API, SKU conflict handling (409), filter type change triggers reload
- [x] 8.4 Write component tests for source-catalog linking: Product column renders dropdown, stale reference shows "(unknown product)", upload link dropdown renders outside DropZone
- [x] 8.5 Test coverage review: evaluate what stable behavior still needs tests, propose and add missing tests using vitest and react-testing-library skills

## 9. Verification

- [x] 9.1 Run Biome lint: `bunx biome check --write .`
- [x] 9.2 Run type check: `bun run check`
- [x] 9.3 Run build: `bun run build`
- [x] 9.4 Run automated tests: `bun run test`
- [x] 9.5 Manual smoke test: all 9 verification scenarios (create, edit, delete, filter, link, unlink, stale ref, upload link, empty states)
- [x] 9.6 Verify installed package versions against `docs/spec.md` minimums
