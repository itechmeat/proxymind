## 1. Backend — Missing Endpoints

- [x] 1.1 Add `SourceListItem` schema to `backend/app/api/source_schemas.py`
- [x] 1.2 Add `GET /api/admin/sources` endpoint to `backend/app/api/admin.py` — list non-deleted sources, ordered by `created_at` DESC, scoped by `agent_id` and `knowledge_base_id`
- [x] 1.3 Write tests for list sources endpoint (`backend/tests/unit/api/test_admin_sources_list.py`)
- [x] 1.4 Add `POST /api/admin/snapshots` endpoint to `backend/app/api/admin.py` — return existing or create new draft via `SnapshotService.get_or_create_draft()`
- [x] 1.5 Write tests for create snapshot endpoint (`backend/tests/unit/api/test_admin_snapshots_create.py`)
- [x] 1.6 Run full backend test suite — verify all existing tests still pass

## 2. Frontend — Types and API Client

- [x] 2.1 Create `frontend/src/types/admin.ts` with TypeScript types for sources, snapshots, tasks, draft test (matching backend schemas)
- [x] 2.2 Create `frontend/src/lib/admin-api.ts` — admin API client functions (getSources, uploadSource, deleteSource, getSnapshots, createSnapshot, publishSnapshot, activateSnapshot, rollbackSnapshot, testDraftSnapshot)
- [x] 2.3 Write tests for admin API client (`frontend/src/tests/lib/admin-api.test.ts`)
- [x] 2.4 Verify types compile with `bunx tsc --noEmit`

## 3. Frontend — UI Primitives

- [x] 3.1 Create `frontend/src/components/ui/badge.tsx` — status badge with color variants (success, warning, error, info, muted)
- [x] 3.2 Create `frontend/src/components/ui/alert-dialog.tsx` — confirmation dialog using Radix AlertDialog
- [x] 3.3 Create `frontend/src/hooks/useToast.ts` — toast state management hook
- [x] 3.4 Create `frontend/src/components/ui/toast.tsx` — toast notification container with auto-dismiss
- [x] 3.5 Create `frontend/src/components/ui/tabs.tsx` — tab navigation using React Router NavLink
- [x] 3.6 Install `@radix-ui/react-alert-dialog` dependency

## 4. Frontend — Admin Routing and Layout

- [x] 4.1 Create `frontend/src/pages/AdminPage/AdminPage.tsx` — admin layout with header, tabs, ToastContext, route outlet, VITE_ADMIN_MODE guard
- [x] 4.2 Update `frontend/src/App.tsx` — add `/admin` routes (index redirect to sources, sources tab, snapshots tab)
- [x] 4.3 Add "Admin" link button to `frontend/src/components/ChatHeader/ChatHeader.tsx` (visible when adminMode=true, separate from existing settings button)
- [x] 4.4 Write admin routing integration tests (`frontend/src/tests/integration/AdminPage.test.tsx`)

## 5. Frontend — Source Management Hooks and Components

- [x] 5.1 Create `frontend/src/hooks/useSources.ts` — source list fetching, 3s polling for PENDING/PROCESSING, upload, delete
- [x] 5.2 Write tests for useSources hook (`frontend/src/tests/hooks/useSources.test.ts`)
- [x] 5.3 Create `frontend/src/components/DropZone/DropZone.tsx` — drag & drop with file validation, click-to-upload fallback
- [x] 5.4 Write tests for DropZone component (`frontend/src/tests/components/DropZone.test.tsx`)
- [x] 5.5 Create `frontend/src/components/SourceList/SourceList.tsx` — table (desktop) / cards (mobile), status badges, delete with AlertDialog
- [x] 5.6 Write tests for SourceList component (`frontend/src/tests/components/SourceList.test.tsx`)
- [x] 5.7 Create `frontend/src/pages/AdminPage/SourcesTab.tsx` — wire DropZone + SourceList + useSources + toast
- [x] 5.8 Wire `SourcesTab` into the `/admin/sources` route in `App.tsx`

## 6. Frontend — Snapshot Management Hooks and Components

- [x] 6.1 Create `frontend/src/hooks/useSnapshots.ts` — snapshot list fetching, create, publish, activate, rollback actions
- [x] 6.2 Write tests for useSnapshots hook (`frontend/src/tests/hooks/useSnapshots.test.ts`)
- [x] 6.3 Create `frontend/src/hooks/useDraftTest.ts` — draft test query and results
- [x] 6.4 Write tests for useDraftTest hook (`frontend/src/tests/hooks/useDraftTest.test.ts`)
- [x] 6.5 Create `frontend/src/components/SnapshotCard/SnapshotCard.tsx` — snapshot card with status-dependent actions and AlertDialog confirmations
- [x] 6.6 Write tests for SnapshotCard component (`frontend/src/tests/components/SnapshotCard.test.tsx`)
- [x] 6.7 Create `frontend/src/components/DraftTestPanel/DraftTestPanel.tsx` — inline search panel with mode selector and results
- [x] 6.8 Write tests for DraftTestPanel component (`frontend/src/tests/components/DraftTestPanel.test.tsx`)
- [x] 6.9 Create `frontend/src/pages/AdminPage/SnapshotsTab.tsx` — wire SnapshotCards + DraftTestPanel + useSnapshots + toast
- [x] 6.10 Wire `SnapshotsTab` into the `/admin/snapshots` route in `App.tsx`

## 7. Final Verification

- [x] 7.1 Run full frontend test suite (`bunx vitest run`) — all tests pass
- [x] 7.2 Run type check (`bunx tsc --noEmit`) — no errors
- [x] 7.3 Run linter (`bunx biome check src/`) — no errors
- [x] 7.4 Run full backend test suite (`python -m pytest --tb=short -q`) — all pass
- [ ] 7.5 Manual smoke test: navigate to /admin/sources, upload a file, verify status polling, delete source
- [ ] 7.6 Manual smoke test: navigate to /admin/snapshots, create draft, test draft search, publish & activate
