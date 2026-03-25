# S5-03: Admin UI — Knowledge Management Design

## Story

Source upload (drag & drop), source list with ingestion statuses, soft delete. Snapshot list, create draft, publish, rollback, draft testing.

**Outcome:** Owner manages sources and knowledge versions through the interface.

**Parallel pair:** S4-06 (Conversation memory) — admin frontend vs backend dialog, zero file overlap.

## Prerequisites

Most backend Admin API endpoints are already implemented:

- Sources: upload (`POST /api/admin/sources`), delete (`DELETE /api/admin/sources/{id}`)
- Snapshots: list (`GET`), detail (`GET`), publish, activate, rollback, test
- Tasks: status polling (`GET /api/admin/tasks/{id}`)
- Batch jobs: create, list, detail

### Backend endpoints that MUST be added before frontend work

Two endpoints are missing and must be added as part of this story (backend-side prerequisite):

1. **`GET /api/admin/sources`** — list non-deleted sources for the selected scope (`agent_id`, `knowledge_base_id` with defaults). Returns the fields needed by the UI: `id`, `title`, `source_type`, `status`, `description`, `public_url`, `file_size_bytes`, `language`, `created_at`. Required for the source list view and polling.

2. **`POST /api/admin/snapshots`** — return the current draft snapshot for the scope, creating it if needed. The backend `SnapshotService` already has `get_or_create_draft()` logic, but it is not exposed via an API endpoint. The endpoint SHOULD return `200 OK` for both the create and reuse paths so it stays a thin wrapper over existing service behavior. Required for the "+ New Draft" button.

These are thin wrappers over existing service logic — no new business logic needed.

## Design Decisions

### 1. Navigation Structure — Top Tabs (Responsive)

**Decision:** Horizontal top tabs within the admin layout.

**Rationale:** For 2-4 sections, tabs are more compact and simpler than a sidebar. Single navigation pattern across all screen sizes. On mobile, tabs span full width (50/50 for two tabs). Adding Catalog tab in S6-02 is trivial extension. If sections exceed 5-6 in the future, migration to sidebar is a localized refactor (YAGNI).

**Rejected alternatives:**

- **Bottom navigation:** Mobile-native pattern, but the user preferred top tabs for consistency with web conventions and easier mobile adaptation via responsive behavior.
- **Sidebar navigation:** Overkill for 2-4 sections. Creates visual noise for a self-hosted tool with one user.
- **Collapsible sidebar:** Added complexity without clear benefit at this stage.

### 2. Tab Organization — Two Tabs with Embedded Upload

**Decision:** Two tabs: Sources (with built-in drag & drop upload zone) and Snapshots.

**Rationale:** Upload and source list in the same view provides immediate feedback — the user uploads a file and sees it appear in the list below with changing status. Minimal cognitive load with only two tabs. Scales well when Catalog tab is added in S6-02.

**Rejected alternatives:**

- **Three tabs (Upload | Sources | Snapshots):** Separating upload from the source list breaks the natural flow of "upload → observe status." User loses context.
- **Two tabs without embedded upload:** Would require a separate modal or page for upload, adding navigation steps.

### 3. Mobile-First Approach

**Decision:** Responsive design with mobile-first breakpoints. Tabs responsive (full-width on mobile). Source list switches from table to card layout on mobile. Draft test mode selector uses dropdown on mobile instead of radio buttons.

### 4. No Optimistic UI

**Decision:** All mutations (delete, publish, rollback) use re-fetch after success response.

**Rationale:** Admin actions have cascading side-effects on the backend (status changes across multiple entities). Optimistic updates would be complex and fragile. The admin UI is not latency-sensitive — a 200ms round-trip for re-fetch is acceptable.

### 5. Access Control

**Decision:** `VITE_ADMIN_MODE=true` env flag gates access to `/admin/*` routes. When false, admin routes redirect to `/`.

**Rationale:** Backend auth (S7-01) is not yet implemented. The env flag provides sufficient access control for local development. Adding real auth later will be a localized change in the route guard.

## Architecture

### Routing

```
/              → ChatPage (existing, unchanged)
/admin         → redirect to /admin/sources
/admin/sources → SourcesTab (upload + source list)
/admin/snapshots → SnapshotsTab (snapshot list + actions + draft test)
```

React Router nested routes with `AdminLayout` as the parent route element.

### Layout

```
Desktop:
┌─────────────────────────────────────┐
│ Admin Header                        │
│ [← Chat]  ProxyMind Admin  [twin]  │
├─────────────────────────────────────┤
│ [Sources]  [Snapshots]              │
├─────────────────────────────────────┤
│                                     │
│  Tab content area (scrollable)      │
│                                     │
└─────────────────────────────────────┘

Mobile:
┌──────────────────────┐
│ [←] ProxyMind Admin  │
├──────────────────────┤
│ [Sources][Snapshots] │  ← full-width 50/50
├──────────────────────┤
│                      │
│  Content (cards)     │
│                      │
└──────────────────────┘
```

### Navigation Between Chat and Admin

- ChatHeader: add a separate "Admin" button/link (visible when `adminMode=true`) that navigates to `/admin`. The existing settings button and `onOpenSettings` callback remain unchanged — they still open the profile edit modal.
- AdminHeader "← Chat" button navigates to `/`

## Sources Tab

### Drop Zone

- Dashed border, icon + instructional text
- Highlighted state when files are dragged over
- Multi-file upload: each file triggers a separate `POST /api/admin/sources`
- On mobile: tap opens native file picker (fallback)
- Upload wire format: `FormData` with `file` field (the file) and `metadata` field (JSON-serialized string). The `metadata` JSON must conform to `SourceUploadMetadata`: `{ title: string (required, 1-255 chars), description?: string, public_url?: string, catalog_item_id?: uuid, language?: string }`. For drag & drop, `title` defaults to filename without extension.
- No metadata modal — KISS. Title is auto-derived from filename.
- The `skip_embedding` query parameter exists on the endpoint (default: `false`). The UI always uses the default — not exposed in the UI.
- Client-side validation before upload:
  - Allowed extensions: `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.png`, `.jpg`, `.jpeg`, `.mp3`, `.wav`, `.mp4`
  - Empty file check
  - Optional client-side soft size limit only if the value is already exposed to the frontend; otherwise rely on the backend `413` response

### Source List

- **Desktop:** Table with columns: title, type (icon), status (badge), actions (delete button)
- **Mobile:** Card stack layout — each card shows title, type badge, status badge, delete button
- Status badges with colors:
  - PENDING — yellow
  - PROCESSING — blue with animated pulse/spinner
  - READY — green
  - FAILED — red
- Sort: newest first (by `created_at`)
- Deleted sources are removed from the list after a successful delete because the list endpoint excludes `DELETED` records by default.

### Polling

```
mount → fetch sources
if any source is PENDING or PROCESSING:
  start interval (3 seconds) → re-fetch sources
when all visible sources are READY or FAILED:
  stop interval
upload completes → re-fetch immediately + start polling
delete completes → re-fetch immediately and remove the source from the rendered list
unmount → cleanup interval
```

### Soft Delete

- Delete button on each source row/card
- AlertDialog confirmation: "Delete source «{title}»? Chunks in published snapshots will remain until replaced."
- `DELETE /api/admin/sources/{id}`
- Backend warnings (e.g., source in published snapshot) shown in toast notification

## Snapshots Tab

### Snapshot List

- Card layout (not table) — each snapshot has different action sets
- Sort order: ACTIVE first, then DRAFT, then PUBLISHED (newest first within group)
- Color indicators: ACTIVE (green), DRAFT (yellow), PUBLISHED (blue), ARCHIVED (gray)
- Each card shows: name, status badge, chunk_count, relevant timestamps
- ARCHIVED hidden by default, toggle "Show archived" at bottom

### Card Information

Each card displays:

- Snapshot name
- Status badge (colored)
- Chunk count
- Timestamps relevant to status (created, published, activated)
- Action buttons based on status

### Actions by Status

| Status    | Actions                           |
| --------- | --------------------------------- |
| DRAFT     | Test, Publish, Publish & Activate |
| PUBLISHED | Activate                          |
| ACTIVE    | Rollback                          |
| ARCHIVED  | (no actions)                      |

### Create Draft

- "+ New Draft" button at top of snapshot list
- `POST /api/admin/snapshots`
- Disabled when a DRAFT already exists (backend constraint: one draft per scope)
- Tooltip on disabled state: "A draft already exists"

### Publish Flow

- "Publish" → AlertDialog confirmation → `POST /api/admin/snapshots/{id}/publish`
- "Publish & Activate" → AlertDialog → `POST /api/admin/snapshots/{id}/publish?activate=true`
- Backend validation errors (no indexed chunks, failed chunks, pending chunks) → error toast with details

### Rollback Flow

- "Rollback" on ACTIVE snapshot → AlertDialog: "Roll back to previous published snapshot «{name}»?"
- `POST /api/admin/snapshots/{id}/rollback`
- Response contains `rolled_back_from` and `rolled_back_to` (both with id, name, status). Use `rolled_back_to.name` for success toast: "Rolled back to «{name}»"
- Success → re-fetch list

### Draft Test Panel (Inline)

- "Test" button on DRAFT card expands an inline panel below the card
- Panel contents:
  - Text input for query
  - Mode selector: Hybrid (default) / Dense / Sparse — radio buttons on desktop, dropdown on mobile
  - Search button
- Results list:
  - Source title, score, anchor metadata (page, chapter, section)
  - Text preview (first 500 characters)
- `POST /api/admin/snapshots/{id}/test` with `{ query, top_n: 5, mode }`

```
┌─ DRAFT ────────────────────────────────┐
│ 📝 v4 "April draft" · 58 chunks       │
│ [Test ▼] [Publish] [Publish & Activate]│
├────────────────────────────────────────┤
│ Query: [___________________] [Search]  │
│ Mode:  (•) Hybrid ( ) Dense ( ) Sparse │
│                                        │
│ Results (5):                           │
│ ┌──────────────────────────────────┐   │
│ │ 📄 "Book Title" · Score: 0.87   │   │
│ │ Chapter 3, p. 42                 │   │
│ │ "Lorem ipsum dolor sit amet..."  │   │
│ └──────────────────────────────────┘   │
└────────────────────────────────────────┘
```

## Data Flow & API Integration

### New API Functions (`lib/admin-api.ts`)

```
Sources:
  getSources(agentId?, kbId?)              → GET /api/admin/sources
  deleteSource(sourceId, agentId?, kbId?)  → DELETE /api/admin/sources/{id}
  uploadSource(file, metadata)             → POST /api/admin/sources

Snapshots:
  getSnapshots(agentId?, kbId?, status?, includeArchived?) → GET /api/admin/snapshots
  createSnapshot(agentId?, kbId?)          → POST /api/admin/snapshots
  publishSnapshot(id, activate?)           → POST /api/admin/snapshots/{id}/publish
  activateSnapshot(id)                     → POST /api/admin/snapshots/{id}/activate
  rollbackSnapshot(id)                     → POST /api/admin/snapshots/{id}/rollback
  testDraftSnapshot(id, query, topN, mode) → POST /api/admin/snapshots/{id}/test

Tasks:
  getTask(taskId)                          → GET /api/admin/tasks/{id}
```

### Custom Hooks

- `useSources()` — source list, polling, upload, delete. Returns `{ sources, isLoading, upload, deleteSource, error }`
- `useSnapshots()` — snapshot list, CRUD actions. Returns `{ snapshots, isLoading, create, publish, activate, rollback, error }`
- `useDraftTest(snapshotId)` — search query and results. Returns `{ results, isSearching, search, error }`

### Error Handling

| Situation                                       | UI Reaction                                                  |
| ----------------------------------------------- | ------------------------------------------------------------ |
| Network error (fetch failed)                    | Toast: "Connection error. Retrying..." + auto-retry after 5s |
| 404 (source/snapshot not found)                 | Toast: "Not found" + remove from local state                 |
| 409 (conflict — snapshot not in expected state) | Toast with backend message + re-fetch list                   |
| 422 (validation — no chunks, pending chunks)    | Toast with error details from backend                        |
| 500 (server error)                              | Toast: "Server error" + error message if available           |
| 413 (file too large, server-side)               | Toast: "File exceeds server size limit"                      |
| Upload: file too large                          | Toast before send (client-side validation)                   |
| Upload: unsupported type                        | Toast before send (client-side validation)                   |

### Toast/Notification Component

- New `ui/toast` component. Lightweight, no heavy library — KISS.
- Types: success (green), error (red), warning (yellow), info (blue)
- Auto-dismiss after 5 seconds, manually closable

## Component Tree & New Files

```
src/
├── pages/
│   └── AdminPage/
│       ├── AdminPage.tsx          # layout: header + tabs + route outlet
│       ├── SourcesTab.tsx         # drop zone + source list
│       └── SnapshotsTab.tsx       # snapshot list + actions
├── components/
│   ├── DropZone/
│   │   └── DropZone.tsx           # drag & drop + file picker fallback
│   ├── SourceList/
│   │   └── SourceList.tsx         # table (desktop) / cards (mobile)
│   ├── SnapshotCard/
│   │   └── SnapshotCard.tsx       # card + status-dependent action buttons
│   ├── DraftTestPanel/
│   │   └── DraftTestPanel.tsx     # inline search + results panel
│   └── ui/
│       ├── tabs.tsx               # tab navigation component
│       ├── badge.tsx              # status badges
│       ├── alert-dialog.tsx       # confirmation dialogs (Radix-based)
│       └── toast.tsx              # notification toasts
├── hooks/
│   ├── useSources.ts             # sources data + polling + mutations
│   ├── useSnapshots.ts           # snapshots data + mutations
│   └── useDraftTest.ts           # draft test query + results
├── types/
│   └── admin.ts                  # TypeScript types for admin domain
└── App.tsx                       # add /admin/* routes
```

### Modified Existing Files

- `App.tsx` — add admin routes with `AdminLayout` wrapper
- `ChatHeader` — add "Admin" button/link (separate from existing settings button)

### No Changes To

- Chat components (MessageBubble, MessageList, CitationsBlock, etc.)
- Chat hooks (useSession)
- Chat transport (ProxyMindTransport)
- Chat types (types/chat.ts)

## Testing Strategy

- **Unit tests:** hooks (useSources, useSnapshots, useDraftTest) with mocked API responses
- **Component tests:** DropZone (drag events, file validation), SourceList (rendering states), SnapshotCard (action buttons per status), DraftTestPanel (search flow)
- **Integration:** AdminPage routing (tab navigation, admin mode guard)
- **No e2e tests** in this story — browser automation deferred

### API query parameter notes

- `DELETE /api/admin/sources/{id}` — `agent_id` and `knowledge_base_id` are **query parameters** (not body), with defaults. Frontend uses defaults.
- `GET /api/admin/snapshots` — filter parameter is `status` (aliased, repeatable for multiple statuses), plus `include_archived: bool` (default false). The "Show archived" toggle maps to `include_archived=true`.

## Out of Scope

- Authentication (S7-01)
- Source detail view (click on source row — YAGNI)
- Bulk operations UI (batch embed — manual via API for now)
- Pagination for source/snapshot lists (sufficient for initial knowledge bases)
- Source metadata editing after upload
