## Context

The chat UI (S5-01, S5-02) lets visitors interact with the twin in the browser. However, the owner still manages sources and snapshots exclusively through raw API calls. Most backend Admin API endpoints already exist (upload, delete, snapshot lifecycle, task status). Two thin endpoints are missing: `GET /api/admin/sources` (list) and `POST /api/admin/snapshots` (create/get draft).

This story adds a browser-based admin UI at `/admin` with two tabs -- Sources (upload + list) and Snapshots (lifecycle management + draft testing) -- plus the two missing backend endpoints.

## Goals

- Admin page with source upload (drag & drop), source list with ingestion status tracking, and soft delete
- Snapshot list with lifecycle actions: create draft, publish, publish & activate, activate, rollback
- Inline draft test panel for verifying retrieval against a draft snapshot
- Navigation link from chat header to admin (and back)
- Two missing backend endpoints as thin wrappers over existing service logic

## Non-Goals

- Authentication / authorization (S7-01)
- Catalog management UI (S6-02)
- Pagination for source or snapshot lists
- Source detail view (click to expand/edit)
- Bulk operations UI (batch embed stays API-only)
- Source metadata editing after upload

## Decisions

### 1. Top tabs navigation (not sidebar or bottom nav)

Horizontal top tabs within `AdminLayout`. For 2-4 sections, tabs are more compact and simpler than a sidebar. Single navigation pattern across screen sizes -- on mobile, tabs span full width (50/50). Adding a Catalog tab in S6-02 is a trivial extension. If sections exceed 5-6 in the future, migration to sidebar is a localized refactor.

Rejected: bottom navigation (mobile-native, inconsistent with web conventions), sidebar (overkill for 2 sections), collapsible sidebar (complexity without benefit).

### 2. Two tabs with embedded upload (not a separate upload page)

Sources tab combines the drag & drop upload zone and the source list in one view. The user uploads a file and immediately sees it appear in the list below with changing status. Minimal cognitive load.

Rejected: three tabs (Upload | Sources | Snapshots) -- separating upload from the source list breaks the natural flow; two tabs without embedded upload -- would require a modal or separate page.

### 3. No optimistic UI

All mutations (delete, publish, rollback) use re-fetch after the success response. Admin actions have cascading side-effects on the backend (status changes across multiple entities). Optimistic updates would be complex and fragile. The admin UI is not latency-sensitive -- a 200ms round-trip for re-fetch is acceptable.

### 4. VITE_ADMIN_MODE environment guard

`VITE_ADMIN_MODE=true` gates access to `/admin/*` routes. When false, admin routes redirect to `/`. This provides sufficient access control for local/self-hosted development. Adding real auth (S7-01) will be a localized change in the route guard.

### 5. Separate admin-api.ts (not modifying api.ts)

Admin API functions live in `lib/admin-api.ts`, separate from the chat transport in `lib/api.ts`. The two API surfaces have different consumers, different error handling patterns, and different auth requirements (future). Keeping them separate avoids coupling and makes the S7-01 auth integration cleaner.

### 6. Polling for status updates (not SSE)

Source ingestion status is tracked via interval polling (3s when any source is PENDING/PROCESSING, stopped when all are terminal). SSE would reduce latency but adds complexity for a single-user admin UI where 3s granularity is sufficient. The backend task status endpoint already exists for polling. SSE can be added later if needed without changing the component API (the `useSources` hook abstracts the refresh mechanism).

### 7. ToastContext for notifications

A lightweight custom toast system (ToastContext + provider) rather than a heavy library. Types: success, error, warning, info. Auto-dismiss after 5s, manually closable. Used for all mutation feedback (upload success, delete confirmation, publish errors, validation failures).

### 8. Responsive design: table to cards on mobile

Source list renders as a table on desktop and a card stack on mobile. Snapshot list uses cards on all breakpoints (each snapshot has different action sets, making a table impractical). Draft test mode selector uses a dropdown on mobile instead of radio buttons.

## Risks / Trade-offs

**Polling overhead.** 3-second polling during active ingestion creates repeated requests. Acceptable for a single-user admin tool. The hook stops polling when all sources reach terminal status, so idle overhead is zero.

**No real auth until S7-01.** The `VITE_ADMIN_MODE` flag is a client-side guard only -- it does not protect the backend Admin API endpoints. Anyone who knows the API endpoints can call them directly. This is acceptable for local/self-hosted deployments where the instance is behind a firewall or VPN. S7-01 will add proper backend auth.

**Two missing backend endpoints.** `GET /api/admin/sources` and `POST /api/admin/snapshots` must be added before the frontend can function. Both are thin wrappers over existing persistence/service logic (`SnapshotService.get_or_create_draft` for snapshots, straightforward scoped source querying for the list endpoint), so risk is low.
