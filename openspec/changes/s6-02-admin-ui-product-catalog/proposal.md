## Story

**S6-02: Admin UI — product catalog** (Phase 6: Commerce)

Verification criteria from `docs/plan.md`:
- Add product → link to source → citation includes purchase link
- Owner manages products through the interface

Stable behavior that must be covered by tests:
- Catalog CRUD operations render correctly (list, create, edit, delete flows)
- Source-catalog linking dropdown works in Sources tab
- Type filter narrows the catalog list
- Stale catalog references display gracefully
- Admin source-product linking completes the UI side of the existing citation-enrichment flow defined in `openspec/specs/citation-enrichment/spec.md`: once a source is linked to an active catalog item, downstream chat/citation rendering can surface the purchase link from that stable contract

## Why

The commerce backend (S6-01) delivers catalog CRUD and source-catalog linking via API, but the admin has no UI to manage products. Without a frontend, the owner must use raw API calls to create products, link them to knowledge sources, and manage the commercial layer. This blocks the full commerce workflow: product → source link → citation enrichment → recommendation.

## What Changes

- Add a third "Catalog" tab to the Admin UI alongside Sources and Snapshots
- Catalog tab: table list of catalog items with type filter, modal dialog for create/edit, soft delete with confirmation
- Edit dialog shows read-only list of linked sources fetched from the detail endpoint
- Sources tab: new "Product" column with inline dropdown for linking/unlinking a catalog item per source
- Upload flow: optional "Link to product" dropdown (outside DropZone) applied to entire batch
- Stale reference handling: if a source references a soft-deleted catalog item not in the active list, the dropdown shows a fallback "(unknown product)" option
- Concrete catalog item types for the filter and badges: Book, Course, Event, Merch, Other

## Catalog Item Types

- `book` — Books and long-form written products
- `course` — Courses, workshops, and learning bundles
- `event` — Conferences, meetups, and live sessions
- `merch` — Physical merchandise and branded goods
- `other` — Catch-all for products that do not fit the main groups

## Capabilities

### New Capabilities
- `catalog-ui`: Admin UI tab for product catalog management — CRUD table, modal form, type filter, delete confirmation, linked sources display

### Modified Capabilities
- `admin-knowledge-ui`: Source list gains a "Product" column with inline catalog-item linking dropdown; upload area gains an optional product-link selector outside the DropZone

## Impact

- **Frontend only** — no backend changes required (S6-01 endpoints are complete)
- New files: `CatalogTab.tsx`, `CatalogList/`, `CatalogFormDialog/`, `useCatalog.ts`
- Modified files: `App.tsx`, `AdminPage.tsx`, `SourcesTab.tsx`, `SourceList.tsx`, `useSources.ts`, `admin-api.ts`, `types/admin.ts`, `locales/en/admin.ts`, `lib/i18n.ts`
- New dependency: none (uses existing Radix UI Dialog, Tailwind, i18next)
- API surface: consumes existing `GET/POST/PATCH/DELETE /api/admin/catalog` and `PATCH /api/admin/sources/:id`
