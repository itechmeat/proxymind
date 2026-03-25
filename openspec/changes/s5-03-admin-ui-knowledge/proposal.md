## Story

**S5-03: Admin UI — knowledge management**

Verification criteria:

- Upload file → see status transition (`pending`/`processing` → terminal status)
- Create snapshot → publish → twin responds
- Rollback → previous version active

Stable behavior that must be covered by tests: admin routing with mode guard, source list with polling, snapshot lifecycle actions (create/publish/rollback), drag & drop upload, draft test search.

## Why

The owner currently manages sources and snapshots exclusively through raw API calls (`curl`, Postman). This is error-prone and requires knowledge of exact endpoints, query parameters, and request formats. A web-based admin UI is the minimum viable interface for non-technical twin operators and makes the product self-contained.

This is the natural next step after the chat UI (S5-01, S5-02) — visitors can already chat with the twin in the browser, but the owner still cannot manage knowledge without CLI tools.

## What Changes

- Add two missing backend endpoints: `GET /api/admin/sources` (list sources) and `POST /api/admin/snapshots` (create/get draft)
- Add `/admin` route tree with dedicated layout, top tabs navigation, and admin mode guard (`VITE_ADMIN_MODE`)
- Sources tab: drag & drop file upload, source list with ingestion status polling, soft delete with confirmation
- Snapshots tab: snapshot cards with status-dependent actions (create draft, publish, publish & activate, activate, rollback), inline draft test panel
- Add "Admin" link button to ChatHeader (visible in admin mode)
- New UI primitives: badge, alert-dialog, toast notifications, tabs

## Capabilities

### New Capabilities

- `admin-knowledge-ui`: Frontend admin interface for knowledge management — source upload, source list with status tracking, snapshot lifecycle management, draft testing. Includes admin routing, layout, and access control via environment flag.

### Modified Capabilities

- `source-upload`: Adding `GET /api/admin/sources` list endpoint (new API surface, existing service logic)
- `snapshot-draft`: Adding `POST /api/admin/snapshots` create/get-draft endpoint (new API surface, existing `get_or_create_draft` service logic)

## Impact

- **Backend**: Two new thin endpoints in `backend/app/api/admin.py`, one new schema in `source_schemas.py`
- **Frontend**: ~15 new files (pages, components, hooks, types), modifications to `App.tsx` and `ChatHeader`
- **Dependencies**: `@radix-ui/react-alert-dialog` (new frontend dependency)
- **No changes to**: chat components, chat transport, chat types, backend services/models
