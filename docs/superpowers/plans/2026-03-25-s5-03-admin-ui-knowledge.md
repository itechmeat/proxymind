# S5-03: Admin UI — Knowledge Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build admin UI for managing knowledge sources and snapshots — upload files, track ingestion, manage snapshot lifecycle, and test draft retrieval.

**Architecture:** Two new backend endpoints (list sources, create snapshot) as thin API wrappers. Frontend: `/admin` route with two tabs (Sources, Snapshots) in a dedicated admin layout. Custom hooks for data fetching/polling/mutations. All admin components are new; existing chat components untouched.

**Tech Stack:** React 19, React Router 7, Tailwind CSS 4, Radix UI (Dialog), Lucide icons, Vitest + Testing Library. Backend: FastAPI, SQLAlchemy, existing services.

**Spec:** `docs/superpowers/specs/2026-03-25-s5-03-admin-ui-knowledge-design.md`

**Git workflow note:** Do not commit from this plan. Keep changes uncommitted for review; a human decides whether and how to commit.

---

## File Map

### Backend (2 new endpoints)

| File                                                    | Action | Responsibility                                     |
| ------------------------------------------------------- | ------ | -------------------------------------------------- |
| `backend/app/api/admin.py`                              | Modify | Add `GET /sources` and `POST /snapshots` endpoints |
| `backend/app/api/source_schemas.py`                     | Modify | Add source list response schema                    |
| `backend/tests/unit/api/test_admin_sources_list.py`     | Create | Tests for list sources endpoint                    |
| `backend/tests/unit/api/test_admin_snapshots_create.py` | Create | Tests for create snapshot endpoint                 |

### Frontend — Types & API

| File                            | Action | Responsibility                                             |
| ------------------------------- | ------ | ---------------------------------------------------------- |
| `frontend/src/types/admin.ts`   | Create | TypeScript types for sources, snapshots, tasks, draft test |
| `frontend/src/lib/admin-api.ts` | Create | Admin API client functions (separate from chat api.ts)     |

### Frontend — UI primitives

| File                                          | Action | Responsibility                             |
| --------------------------------------------- | ------ | ------------------------------------------ |
| `frontend/src/components/ui/badge.tsx`        | Create | Status badge component with color variants |
| `frontend/src/components/ui/alert-dialog.tsx` | Create | Confirmation dialog (Radix AlertDialog)    |
| `frontend/src/components/ui/toast.tsx`        | Create | Toast notification system                  |
| `frontend/src/components/ui/tabs.tsx`         | Create | Tab navigation component                   |

### Frontend — Admin pages & components

| File                                                        | Action | Responsibility                              |
| ----------------------------------------------------------- | ------ | ------------------------------------------- |
| `frontend/src/pages/AdminPage/AdminPage.tsx`                | Create | Admin layout: header + tabs + route outlet  |
| `frontend/src/pages/AdminPage/SourcesTab.tsx`               | Create | Sources tab: drop zone + source list        |
| `frontend/src/pages/AdminPage/SnapshotsTab.tsx`             | Create | Snapshots tab: snapshot cards + actions     |
| `frontend/src/components/DropZone/DropZone.tsx`             | Create | Drag & drop file upload zone                |
| `frontend/src/components/SourceList/SourceList.tsx`         | Create | Source table (desktop) / cards (mobile)     |
| `frontend/src/components/SnapshotCard/SnapshotCard.tsx`     | Create | Snapshot card with status-dependent actions |
| `frontend/src/components/DraftTestPanel/DraftTestPanel.tsx` | Create | Inline draft test search panel              |

### Frontend — Hooks

| File                                 | Action | Responsibility                       |
| ------------------------------------ | ------ | ------------------------------------ |
| `frontend/src/hooks/useSources.ts`   | Create | Source list, polling, upload, delete |
| `frontend/src/hooks/useSnapshots.ts` | Create | Snapshot list, CRUD mutations        |
| `frontend/src/hooks/useDraftTest.ts` | Create | Draft test query and results         |
| `frontend/src/hooks/useToast.ts`     | Create | Toast state management               |

### Frontend — Modified existing files

| File                                                | Action | Change                  |
| --------------------------------------------------- | ------ | ----------------------- |
| `frontend/src/App.tsx`                              | Modify | Add `/admin/*` routes   |
| `frontend/src/components/ChatHeader/ChatHeader.tsx` | Modify | Add "Admin" link button |

### Frontend — Tests

| File                                                    | Action | Responsibility                                  |
| ------------------------------------------------------- | ------ | ----------------------------------------------- |
| `frontend/src/tests/lib/admin-api.test.ts`              | Create | Admin API client tests                          |
| `frontend/src/tests/hooks/useSources.test.ts`           | Create | Source hook: fetch, poll, upload, delete        |
| `frontend/src/tests/hooks/useSnapshots.test.ts`         | Create | Snapshot hook: fetch, create, publish, rollback |
| `frontend/src/tests/hooks/useDraftTest.test.ts`         | Create | Draft test hook                                 |
| `frontend/src/tests/components/DropZone.test.tsx`       | Create | Drag/drop events, file validation               |
| `frontend/src/tests/components/SourceList.test.tsx`     | Create | Rendering states, delete action                 |
| `frontend/src/tests/components/SnapshotCard.test.tsx`   | Create | Actions per status                              |
| `frontend/src/tests/components/DraftTestPanel.test.tsx` | Create | Search flow, result rendering                   |
| `frontend/src/tests/integration/AdminPage.test.tsx`     | Create | Routing, tab navigation, admin mode guard       |

---

## Task 1: Backend — List Sources Endpoint

**Files:**

- Modify: `backend/app/api/admin.py`
- Create: `backend/tests/unit/api/test_admin_sources_list.py`

- [ ] **Step 1: Write failing test for list sources**

```python
# backend/tests/unit/api/test_admin_sources_list.py
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_list_sources_empty(async_client: AsyncClient):
    """GET /api/admin/sources returns empty list when no sources exist."""
    response = await async_client.get("/api/admin/sources")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_sources_returns_sources(async_client: AsyncClient, seeded_source):
    """GET /api/admin/sources returns sources with expected fields."""
    response = await async_client.get("/api/admin/sources")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    source = data[0]
    assert "id" in source
    assert "title" in source
    assert "source_type" in source
    assert "status" in source
    assert "created_at" in source


async def test_list_sources_excludes_deleted(async_client: AsyncClient, deleted_source):
    """GET /api/admin/sources excludes deleted sources by default."""
    response = await async_client.get("/api/admin/sources")
    assert response.status_code == 200
    ids = [s["id"] for s in response.json()]
    assert str(deleted_source.id) not in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/api/test_admin_sources_list.py -v`
Expected: FAIL — 404 (no route)

- [ ] **Step 3: Add response schema**

Add to `backend/app/api/source_schemas.py`:

```python
class SourceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: SourceStatus
    description: str | None
    public_url: str | None
    file_size_bytes: int | None
    language: str | None
    created_at: datetime
```

- [ ] **Step 4: Add GET /sources endpoint**

Add to `backend/app/api/admin.py`:

```python
@router.get("/sources", response_model=list[SourceListItem])
async def list_sources(
    session: Annotated[AsyncSession, Depends(get_session)],
    agent_id: uuid.UUID = Query(default=DEFAULT_AGENT_ID),
    knowledge_base_id: uuid.UUID = Query(default=DEFAULT_KNOWLEDGE_BASE_ID),
) -> list[SourceListItem]:
    """List all non-deleted sources for the given scope."""
    result = await session.scalars(
        select(Source)
        .where(
            Source.agent_id == agent_id,
            Source.knowledge_base_id == knowledge_base_id,
            Source.status != SourceStatus.DELETED,
        )
        .order_by(Source.created_at.desc())
    )
    return [SourceListItem.model_validate(source) for source in result.all()]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/api/test_admin_sources_list.py -v`
Expected: PASS

---

## Task 2: Backend — Create Snapshot Endpoint

**Files:**

- Modify: `backend/app/api/admin.py`
- Create: `backend/tests/unit/api/test_admin_snapshots_create.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/api/test_admin_snapshots_create.py
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_create_draft_snapshot(async_client: AsyncClient):
    """POST /api/admin/snapshots creates a new draft snapshot."""
    response = await async_client.post("/api/admin/snapshots")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "draft"
    assert "id" in data
    assert "name" in data


async def test_create_draft_returns_existing(async_client: AsyncClient):
    """POST /api/admin/snapshots returns existing draft if one exists."""
    r1 = await async_client.post("/api/admin/snapshots")
    r2 = await async_client.post("/api/admin/snapshots")
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/api/test_admin_snapshots_create.py -v`
Expected: FAIL — 405 Method Not Allowed (no POST route)

- [ ] **Step 3: Add POST /snapshots endpoint**

Add to `backend/app/api/admin.py`:

```python
@router.post("/snapshots", response_model=SnapshotResponse)
async def create_snapshot(
    agent_id: uuid.UUID = Query(default=DEFAULT_AGENT_ID),
    knowledge_base_id: uuid.UUID = Query(default=DEFAULT_KNOWLEDGE_BASE_ID),
    snapshot_service: SnapshotService = Depends(get_snapshot_service),
):
    """Create a new draft snapshot, or return the existing draft."""
    snapshot = await snapshot_service.get_or_create_draft(
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/api/test_admin_snapshots_create.py -v`
Expected: PASS

- [ ] **Step 5: Run full backend test suite**

Run: `cd backend && python -m pytest --tb=short -q`
Expected: all existing tests still pass

---

## Task 3: Frontend — Admin Types

**Files:**

- Create: `frontend/src/types/admin.ts`

- [ ] **Step 1: Create TypeScript types**

```typescript
// frontend/src/types/admin.ts

// ── Source types ──

export type SourceType = "markdown" | "txt" | "pdf" | "docx" | "html" | "image" | "audio" | "video";

export type SourceStatus = "pending" | "processing" | "ready" | "failed" | "deleted";

export interface SourceListItem {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
  description: string | null;
  public_url: string | null;
  file_size_bytes: number | null;
  language: string | null;
  created_at: string;
}

export interface SourceUploadResponse {
  source_id: string;
  task_id: string;
  status: string;
  file_path: string;
  message: string;
}

export interface SourceDeleteResponse {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
  deleted_at: string | null;
  warnings: string[];
}

// ── Snapshot types ──

export type SnapshotStatus = "draft" | "published" | "active" | "archived";

export interface SnapshotResponse {
  id: string;
  agent_id: string | null;
  knowledge_base_id: string | null;
  name: string;
  description: string | null;
  status: SnapshotStatus;
  published_at: string | null;
  activated_at: string | null;
  archived_at: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface RollbackSnapshotResponse {
  id: string;
  name: string;
  status: SnapshotStatus;
  published_at: string | null;
  activated_at: string | null;
}

export interface RollbackResponse {
  rolled_back_from: RollbackSnapshotResponse;
  rolled_back_to: RollbackSnapshotResponse;
}

// ── Draft test types ──

export type RetrievalMode = "hybrid" | "dense" | "sparse";

export interface DraftTestAnchor {
  page: number | null;
  chapter: string | null;
  section: string | null;
  timecode: string | null;
}

export interface DraftTestResult {
  chunk_id: string;
  source_id: string;
  source_title: string | null;
  text_content: string;
  score: number;
  anchor: DraftTestAnchor;
}

export interface DraftTestResponse {
  snapshot_id: string;
  snapshot_name: string;
  query: string;
  mode: RetrievalMode;
  results: DraftTestResult[];
  total_chunks_in_draft: number;
}

// ── Task types ──

export interface TaskStatusResponse {
  id: string;
  task_type: string;
  status: string;
  source_id: string | null;
  progress: number | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd frontend && bunx tsc --noEmit`
Expected: no errors

---

## Task 4: Frontend — Admin API Client

**Files:**

- Create: `frontend/src/lib/admin-api.ts`
- Create: `frontend/src/tests/lib/admin-api.test.ts`

- [ ] **Step 1: Write failing tests for admin API client**

```typescript
// frontend/src/tests/lib/admin-api.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { activateSnapshot, createSnapshot, deleteSource, getSources, getSnapshots, publishSnapshot, rollbackSnapshot, testDraftSnapshot, uploadSource } from "@/lib/admin-api";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("admin-api", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("getSources fetches source list", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    const result = await getSources();
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/sources", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    expect(result).toEqual([]);
  });

  it("uploadSource sends FormData with metadata JSON", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          source_id: "s-1",
          task_id: "t-1",
          status: "pending",
          file_path: "/files/doc.md",
          message: "ok",
        },
        202,
      ),
    );

    const file = new File(["content"], "doc.md", { type: "text/markdown" });
    await uploadSource(file, { title: "doc" });

    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/sources");
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
    const formData = opts.body as FormData;
    expect(formData.get("file")).toBe(file);
    expect(JSON.parse(formData.get("metadata") as string)).toEqual({
      title: "doc",
    });
  });

  it("deleteSource calls DELETE with source id", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "s-1",
        title: "doc",
        source_type: "markdown",
        status: "deleted",
        deleted_at: "2026-03-25T12:00:00Z",
        warnings: [],
      }),
    );

    await deleteSource("s-1");
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/sources/s-1", {
      method: "DELETE",
      headers: { Accept: "application/json" },
    });
  });

  it("getSnapshots fetches snapshot list", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await getSnapshots();
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/snapshots", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  });

  it("getSnapshots with includeArchived passes query param", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    await getSnapshots(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/snapshots?include_archived=true", { method: "GET", headers: { Accept: "application/json" } });
  });

  it("activateSnapshot calls POST activate", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "snap-1", status: "active" }));
    await activateSnapshot("snap-1");
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/snapshots/snap-1/activate", { method: "POST", headers: { Accept: "application/json" } });
  });

  it("createSnapshot sends POST", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "snap-1", status: "draft", name: "Draft", chunk_count: 0 }));
    await createSnapshot();
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/snapshots", {
      method: "POST",
      headers: { Accept: "application/json" },
    });
  });

  it("publishSnapshot with activate flag", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "snap-1", status: "active" }));
    await publishSnapshot("snap-1", true);
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/snapshots/snap-1/publish?activate=true", { method: "POST", headers: { Accept: "application/json" } });
  });

  it("rollbackSnapshot calls POST rollback", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        rolled_back_from: { id: "snap-2", name: "v2", status: "published" },
        rolled_back_to: { id: "snap-1", name: "v1", status: "active" },
      }),
    );
    await rollbackSnapshot("snap-2");
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/snapshots/snap-2/rollback", { method: "POST", headers: { Accept: "application/json" } });
  });

  it("testDraftSnapshot sends query and mode", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        snapshot_id: "snap-1",
        snapshot_name: "Draft",
        query: "test",
        mode: "hybrid",
        results: [],
        total_chunks_in_draft: 10,
      }),
    );
    await testDraftSnapshot("snap-1", "test", 5, "hybrid");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/snapshots/snap-1/test");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ query: "test", top_n: 5, mode: "hybrid" });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bunx vitest run src/tests/lib/admin-api.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement admin API client**

```typescript
// frontend/src/lib/admin-api.ts
import { buildApiUrl, ApiError } from "@/lib/api";
import type { DraftTestResponse, RetrievalMode, RollbackResponse, SnapshotResponse, SourceDeleteResponse, SourceListItem, SourceUploadResponse } from "@/types/admin";

async function parseJson<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  let detail = `Request failed (${response.status})`;
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) {
      detail = body.detail;
    }
  } catch {
    // Use status-based fallback.
  }

  throw new ApiError(response.status, detail);
}

// ── Sources ──

export async function getSources(): Promise<SourceListItem[]> {
  const response = await fetch(buildApiUrl("/api/admin/sources"), {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return parseJson<SourceListItem[]>(response);
}

export async function uploadSource(file: File, metadata: { title: string; description?: string; public_url?: string; language?: string }): Promise<SourceUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("metadata", JSON.stringify(metadata));

  const response = await fetch(buildApiUrl("/api/admin/sources"), {
    method: "POST",
    body: formData,
  });
  return parseJson<SourceUploadResponse>(response);
}

export async function deleteSource(sourceId: string): Promise<SourceDeleteResponse> {
  const response = await fetch(buildApiUrl(`/api/admin/sources/${encodeURIComponent(sourceId)}`), { method: "DELETE", headers: { Accept: "application/json" } });
  return parseJson<SourceDeleteResponse>(response);
}

// ── Snapshots ──

export async function getSnapshots(includeArchived = false): Promise<SnapshotResponse[]> {
  const params = includeArchived ? "?include_archived=true" : "";
  const response = await fetch(buildApiUrl(`/api/admin/snapshots${params}`), {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return parseJson<SnapshotResponse[]>(response);
}

export async function createSnapshot(): Promise<SnapshotResponse> {
  const response = await fetch(buildApiUrl("/api/admin/snapshots"), {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  return parseJson<SnapshotResponse>(response);
}

export async function publishSnapshot(snapshotId: string, activate = false): Promise<SnapshotResponse> {
  const params = activate ? "?activate=true" : "";
  const response = await fetch(buildApiUrl(`/api/admin/snapshots/${encodeURIComponent(snapshotId)}/publish${params}`), { method: "POST", headers: { Accept: "application/json" } });
  return parseJson<SnapshotResponse>(response);
}

export async function activateSnapshot(snapshotId: string): Promise<SnapshotResponse> {
  const response = await fetch(buildApiUrl(`/api/admin/snapshots/${encodeURIComponent(snapshotId)}/activate`), { method: "POST", headers: { Accept: "application/json" } });
  return parseJson<SnapshotResponse>(response);
}

export async function rollbackSnapshot(snapshotId: string): Promise<RollbackResponse> {
  const response = await fetch(buildApiUrl(`/api/admin/snapshots/${encodeURIComponent(snapshotId)}/rollback`), { method: "POST", headers: { Accept: "application/json" } });
  return parseJson<RollbackResponse>(response);
}

export async function testDraftSnapshot(snapshotId: string, query: string, topN: number, mode: RetrievalMode): Promise<DraftTestResponse> {
  const response = await fetch(buildApiUrl(`/api/admin/snapshots/${encodeURIComponent(snapshotId)}/test`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_n: topN, mode }),
  });
  return parseJson<DraftTestResponse>(response);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bunx vitest run src/tests/lib/admin-api.test.ts`
Expected: PASS

---

## Task 5: Frontend — UI Primitives (Badge, AlertDialog, Toast, Tabs)

**Files:**

- Create: `frontend/src/components/ui/badge.tsx`
- Create: `frontend/src/components/ui/alert-dialog.tsx`
- Create: `frontend/src/components/ui/toast.tsx`
- Create: `frontend/src/components/ui/tabs.tsx`
- Create: `frontend/src/hooks/useToast.ts`

These are base UI components following existing `ui/` patterns (button.tsx, avatar.tsx). They use Tailwind + CVA for variants, Radix primitives where applicable.

- [ ] **Step 1: Create Badge component**

```tsx
// frontend/src/components/ui/badge.tsx
import { type VariantProps, cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      default: "bg-zinc-800 text-zinc-300",
      success: "bg-emerald-900/50 text-emerald-400",
      warning: "bg-amber-900/50 text-amber-400",
      error: "bg-red-900/50 text-red-400",
      info: "bg-blue-900/50 text-blue-400",
      muted: "bg-zinc-800/50 text-zinc-500",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
```

- [ ] **Step 2: Create AlertDialog component**

Use Radix AlertDialog (already have `@radix-ui/react-dialog` installed — check if `@radix-ui/react-alert-dialog` is needed or use the existing Dialog):

```tsx
// frontend/src/components/ui/alert-dialog.tsx
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { cn } from "@/lib/utils";

// Install first if needed: bun add @radix-ui/react-alert-dialog

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;

export function AlertDialogContent({ className, children, ...props }: AlertDialogPrimitive.AlertDialogContentProps) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60" />
      <AlertDialogPrimitive.Content className={cn("fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-zinc-800 bg-zinc-900 p-6 shadow-lg", className)} {...props}>
        {children}
      </AlertDialogPrimitive.Content>
    </AlertDialogPrimitive.Portal>
  );
}

export const AlertDialogTitle = AlertDialogPrimitive.Title;
export const AlertDialogDescription = AlertDialogPrimitive.Description;
export const AlertDialogAction = AlertDialogPrimitive.Action;
export const AlertDialogCancel = AlertDialogPrimitive.Cancel;
```

- [ ] **Step 3: Create Toast system**

```tsx
// frontend/src/hooks/useToast.ts
import { useCallback, useState } from "react";

export type ToastVariant = "success" | "error" | "warning" | "info";

export interface Toast {
  id: string;
  message: string;
  variant: ToastVariant;
}

let counter = 0;

export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, variant: ToastVariant = "info") => {
    const id = `toast-${++counter}`;
    setToasts((prev) => [...prev, { id, message, variant }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, addToast, removeToast };
}
```

```tsx
// frontend/src/components/ui/toast.tsx
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Toast as ToastType, ToastVariant } from "@/hooks/useToast";

const variantClasses: Record<ToastVariant, string> = {
  success: "border-emerald-800 bg-emerald-950 text-emerald-300",
  error: "border-red-800 bg-red-950 text-red-300",
  warning: "border-amber-800 bg-amber-950 text-amber-300",
  info: "border-blue-800 bg-blue-950 text-blue-300",
};

interface ToastProps {
  toast: ToastType;
  onDismiss: (id: string) => void;
}

function Toast({ toast, onDismiss }: ToastProps) {
  return (
    <div className={cn("flex items-center gap-2 rounded-lg border px-4 py-3 text-sm shadow-lg", variantClasses[toast.variant])} role="alert">
      <span className="flex-1">{toast.message}</span>
      <button aria-label="Dismiss" className="shrink-0 opacity-70 hover:opacity-100" onClick={() => onDismiss(toast.id)} type="button">
        <X size={14} />
      </button>
    </div>
  );
}

interface ToastContainerProps {
  toasts: ToastType[];
  onDismiss: (id: string) => void;
}

export function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <Toast key={toast.id} onDismiss={onDismiss} toast={toast} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create Tabs component**

```tsx
// frontend/src/components/ui/tabs.tsx
import { NavLink } from "react-router";
import { cn } from "@/lib/utils";

interface Tab {
  label: string;
  to: string;
}

interface TabsProps {
  tabs: Tab[];
}

export function Tabs({ tabs }: TabsProps) {
  return (
    <nav className="flex border-b border-zinc-800">
      {tabs.map((tab) => (
        <NavLink className={({ isActive }) => cn("px-4 py-2 text-sm font-medium transition-colors", isActive ? "border-b-2 border-zinc-100 text-zinc-100" : "text-zinc-400 hover:text-zinc-200")} end key={tab.to} to={tab.to}>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
```

- [ ] **Step 5: Check dependencies — install @radix-ui/react-alert-dialog if needed**

Run: `cd frontend && bun add @radix-ui/react-alert-dialog`

- [ ] **Step 6: Verify types compile**

Run: `cd frontend && bunx tsc --noEmit`
Expected: no errors

---

## Task 6: Frontend — Admin Routing & Layout

**Files:**

- Create: `frontend/src/pages/AdminPage/AdminPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ChatHeader/ChatHeader.tsx`
- Create: `frontend/src/tests/integration/AdminPage.test.tsx`

- [ ] **Step 1: Write failing test for admin routing**

```tsx
// frontend/src/tests/integration/AdminPage.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import App from "@/App";

vi.mock("@/lib/config", () => ({
  appConfig: {
    apiUrl: "",
    adminMode: true,
    language: "en",
    twinName: "Test Twin",
    twinAvatarUrl: "",
  },
}));

describe("admin routing", () => {
  it("renders admin layout at /admin/sources", () => {
    render(
      <MemoryRouter initialEntries={["/admin/sources"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("Snapshots")).toBeInTheDocument();
  });

  it("redirects /admin to /admin/sources", () => {
    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Sources")).toBeInTheDocument();
  });
});
```

**Important:** `App` currently renders `<BrowserRouter>` internally, so wrapping in `<MemoryRouter>` would cause a nested router error. Solution: extract the `<Routes>` block from `App.tsx` into a separate `AppRoutes` component (no router wrapper). `App` renders `<BrowserRouter><AppRoutes /></BrowserRouter>`. Tests render `<MemoryRouter initialEntries={[...]}><AppRoutes /></MemoryRouter>`. Follow the existing `ChatPage.test.tsx` pattern for reference.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && bunx vitest run src/tests/integration/AdminPage.test.tsx`
Expected: FAIL — no admin route

- [ ] **Step 3: Create AdminPage layout**

```tsx
// frontend/src/pages/AdminPage/AdminPage.tsx
import { ArrowLeft } from "lucide-react";
import { Navigate, Outlet, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { appConfig } from "@/lib/config";

const adminTabs = [
  { label: "Sources", to: "/admin/sources" },
  { label: "Snapshots", to: "/admin/snapshots" },
];

// Toast context so SourcesTab/SnapshotsTab can show toasts
interface ToastContextValue {
  addToast: (message: string, variant: ToastVariant) => void;
}

export const ToastContext = React.createContext<ToastContextValue>({
  addToast: () => {},
});

export function AdminPage() {
  const navigate = useNavigate();
  const { toasts, addToast, removeToast } = useToast();

  if (!appConfig.adminMode) {
    return <Navigate replace to="/" />;
  }

  return (
    <ToastContext.Provider value={{ addToast }}>
      <div className="flex h-dvh flex-col bg-zinc-950 text-zinc-100">
        <header className="flex items-center gap-3 border-b border-zinc-800 px-4 py-3">
          <Button aria-label="Back to chat" onClick={() => navigate("/")} size="icon-sm" variant="ghost">
            <ArrowLeft size={18} />
          </Button>
          <h1 className="text-lg font-semibold">ProxyMind Admin</h1>
        </header>

        <Tabs tabs={adminTabs} />

        <main className="flex-1 overflow-y-auto p-4">
          <Outlet />
        </main>

        <ToastContainer onDismiss={removeToast} toasts={toasts} />
      </div>
    </ToastContext.Provider>
  );
}
```

- [ ] **Step 4: Update App.tsx with admin routes**

```tsx
// frontend/src/App.tsx
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { ChatPage } from "@/pages/ChatPage";
import { AdminPage } from "@/pages/AdminPage/AdminPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<ChatPage />} path="/" />
        <Route element={<AdminPage />} path="/admin">
          <Route index element={<Navigate replace to="sources" />} />
          <Route path="sources" element={<div>Sources placeholder</div>} />
          <Route path="snapshots" element={<div>Snapshots placeholder</div>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
```

- [ ] **Step 5: Add Admin link to ChatHeader**

Add an admin link button next to the existing settings button in `ChatHeader.tsx`. Import `Link` from `react-router` and add a new button inside `chat-header__actions` that links to `/admin`, using a layout icon (e.g., `LayoutDashboard` from Lucide).

- [ ] **Step 6: Run tests**

Run: `cd frontend && bunx vitest run src/tests/integration/AdminPage.test.tsx`
Expected: PASS (adjust test if needed based on router setup)

- [ ] **Step 7: Verify types compile and existing tests still pass**

Run: `cd frontend && bunx tsc --noEmit && bunx vitest run`
Expected: all pass

---

## Task 7: Frontend — useSources Hook

**Files:**

- Create: `frontend/src/hooks/useSources.ts`
- Create: `frontend/src/tests/hooks/useSources.test.ts`

- [ ] **Step 1: Write failing tests**

Test cases:

1. Fetches sources on mount
2. Starts polling when sources are in pending/processing status
3. Stops polling when all sources are in final status
4. `upload` sends file and re-fetches
5. `remove` calls delete and re-fetches
6. Cleans up interval on unmount

```typescript
// frontend/src/tests/hooks/useSources.test.ts
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/admin-api");

import * as adminApi from "@/lib/admin-api";
import { useSources } from "@/hooks/useSources";
import type { SourceListItem } from "@/types/admin";

const mockGetSources = vi.mocked(adminApi.getSources);
const mockUploadSource = vi.mocked(adminApi.uploadSource);
const mockDeleteSource = vi.mocked(adminApi.deleteSource);

const readySource: SourceListItem = {
  id: "s-1",
  title: "Doc",
  source_type: "markdown",
  status: "ready",
  description: null,
  public_url: null,
  file_size_bytes: 100,
  language: null,
  created_at: "2026-03-25T12:00:00Z",
};

describe("useSources", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  it("fetches sources on mount", async () => {
    mockGetSources.mockResolvedValueOnce([readySource]);
    const { result } = renderHook(() => useSources());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.sources).toEqual([readySource]);
  });

  it("polls when sources are processing", async () => {
    const processingSource = { ...readySource, status: "processing" as const };
    mockGetSources.mockResolvedValueOnce([processingSource]).mockResolvedValueOnce([readySource]);

    const { result } = renderHook(() => useSources());

    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    await waitFor(() => {
      expect(result.current.sources[0]?.status).toBe("ready");
    });
    expect(mockGetSources).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bunx vitest run src/tests/hooks/useSources.test.ts`
Expected: FAIL

- [ ] **Step 3: Implement useSources hook**

```typescript
// frontend/src/hooks/useSources.ts
import { useCallback, useEffect, useRef, useState } from "react";
import * as adminApi from "@/lib/admin-api";
import type { SourceListItem } from "@/types/admin";

const POLL_INTERVAL_MS = 3000;

function hasActiveIngestion(sources: SourceListItem[]): boolean {
  return sources.some((s) => s.status === "pending" || s.status === "processing");
}

export function useSources() {
  const [sources, setSources] = useState<SourceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchSources = useCallback(async () => {
    try {
      const data = await adminApi.getSources();
      setSources(data);
      setError(null);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sources");
      return null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (intervalRef.current) return;
    intervalRef.current = setInterval(async () => {
      const data = await fetchSources();
      if (data && !hasActiveIngestion(data)) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    }, POLL_INTERVAL_MS);
  }, [fetchSources]);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await fetchSources();
      if (!cancelled) {
        setIsLoading(false);
        if (data && hasActiveIngestion(data)) {
          startPolling();
        }
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [fetchSources, startPolling, stopPolling]);

  const upload = useCallback(
    async (file: File) => {
      const title = file.name.replace(/\.[^.]+$/, "");
      const result = await adminApi.uploadSource(file, { title });
      const data = await fetchSources();
      if (data && hasActiveIngestion(data)) {
        startPolling();
      }
      return result;
    },
    [fetchSources, startPolling],
  );

  const remove = useCallback(
    async (sourceId: string) => {
      const result = await adminApi.deleteSource(sourceId);
      await fetchSources();
      return result;
    },
    [fetchSources],
  );

  return { sources, isLoading, error, upload, remove };
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && bunx vitest run src/tests/hooks/useSources.test.ts`
Expected: PASS

---

## Task 8: Frontend — useSnapshots Hook

**Files:**

- Create: `frontend/src/hooks/useSnapshots.ts`
- Create: `frontend/src/tests/hooks/useSnapshots.test.ts`

- [ ] **Step 1: Write failing tests**

Test cases: fetch on mount, create draft, publish, publish & activate, rollback, activate, error handling.

- [ ] **Step 2: Implement useSnapshots hook**

Pattern: similar to `useSources` but no polling needed. State: `snapshots`, `isLoading`, `error`. Actions: `create`, `publish`, `activate`, `rollback`. Each action calls API then re-fetches list.

- [ ] **Step 3: Run tests, verify pass**

Run: `cd frontend && bunx vitest run src/tests/hooks/useSnapshots.test.ts`

---

## Task 9: Frontend — useDraftTest Hook

**Files:**

- Create: `frontend/src/hooks/useDraftTest.ts`
- Create: `frontend/src/tests/hooks/useDraftTest.test.ts`

- [ ] **Step 1: Write failing tests**

Test cases: search returns results, search with different modes, error handling, loading state.

- [ ] **Step 2: Implement useDraftTest hook**

State: `results` (DraftTestResponse | null), `isSearching`, `error`. Action: `search(query, topN, mode)`.

- [ ] **Step 3: Run tests, verify pass**

Run: `cd frontend && bunx vitest run src/tests/hooks/useDraftTest.test.ts`

---

## Task 10: Frontend — DropZone Component

**Files:**

- Create: `frontend/src/components/DropZone/DropZone.tsx`
- Create: `frontend/src/tests/components/DropZone.test.tsx`

- [ ] **Step 1: Write failing tests**

Test cases:

1. Renders drop zone with instructional text
2. Calls `onFilesSelected` with valid files on drop
3. Rejects files with unsupported extensions (shows validation error)
4. Opens file picker on click
5. Accepts multiple files

- [ ] **Step 2: Implement DropZone**

Props: `onFilesSelected: (files: File[]) => void`, `disabled?: boolean`.
Features: drag enter/leave/over/drop handlers, `<input type="file" multiple>` hidden behind the zone, file extension validation (`.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.png`, `.jpg`, `.jpeg`, `.mp3`, `.wav`, `.mp4`), visual drag-over state.

- [ ] **Step 3: Run tests, verify pass**

Run: `cd frontend && bunx vitest run src/tests/components/DropZone.test.tsx`

---

## Task 11: Frontend — SourceList Component

**Files:**

- Create: `frontend/src/components/SourceList/SourceList.tsx`
- Create: `frontend/src/tests/components/SourceList.test.tsx`

- [ ] **Step 1: Write failing tests**

Test cases:

1. Renders source items with title, type, status badge
2. PROCESSING sources show animated indicator
3. FAILED sources show error badge
4. Delete button triggers `onDelete` callback
5. Empty list shows "No sources" message

- [ ] **Step 2: Implement SourceList**

Props: `sources: SourceListItem[]`, `onDelete: (id: string) => void`.
Uses Badge for status colors. Maps `source_type` to Lucide icon. Each row has title, type icon, status badge, delete button. Delete button wrapped in AlertDialog for confirmation.

- [ ] **Step 3: Run tests, verify pass**

Run: `cd frontend && bunx vitest run src/tests/components/SourceList.test.tsx`

---

## Task 12: Frontend — SourcesTab (Wiring DropZone + SourceList)

**Files:**

- Create: `frontend/src/pages/AdminPage/SourcesTab.tsx`
- Modify: `frontend/src/App.tsx` — replace placeholder with `<SourcesTab />`

- [ ] **Step 1: Implement SourcesTab**

Wires `useSources` hook → `DropZone` + `SourceList`. Handles upload errors with toast. Shows loading state.

- [ ] **Step 2: Update App.tsx route**

Replace `<div>Sources placeholder</div>` with `<SourcesTab />`.

- [ ] **Step 3: Manual smoke test**

Run: `cd frontend && bun dev`
Navigate to `/admin/sources` — should show drop zone and empty source list.

---

## Task 13: Frontend — SnapshotCard Component

**Files:**

- Create: `frontend/src/components/SnapshotCard/SnapshotCard.tsx`
- Create: `frontend/src/tests/components/SnapshotCard.test.tsx`

- [ ] **Step 1: Write failing tests**

Test cases:

1. DRAFT card shows Test, Publish, Publish & Activate buttons
2. PUBLISHED card shows Activate button
3. ACTIVE card shows Rollback button
4. ARCHIVED card shows no action buttons
5. Card shows name, status badge, chunk count, timestamps

- [ ] **Step 2: Implement SnapshotCard**

Props: `snapshot: SnapshotResponse`, `onPublish`, `onActivate`, `onRollback`, `onTest`. Shows status-dependent buttons. Each destructive action (Publish, Rollback) wrapped in AlertDialog. Uses Badge for status.

- [ ] **Step 3: Run tests, verify pass**

Run: `cd frontend && bunx vitest run src/tests/components/SnapshotCard.test.tsx`

---

## Task 14: Frontend — DraftTestPanel Component

**Files:**

- Create: `frontend/src/components/DraftTestPanel/DraftTestPanel.tsx`
- Create: `frontend/src/tests/components/DraftTestPanel.test.tsx`

- [ ] **Step 1: Write failing tests**

Test cases:

1. Renders query input and search button
2. Renders mode selector (Hybrid/Dense/Sparse)
3. Calls `onSearch` with query and mode on submit
4. Displays results with source title, score, text preview, anchor
5. Shows loading state during search
6. Shows empty state when no results

- [ ] **Step 2: Implement DraftTestPanel**

Props: `snapshotId: string`, uses `useDraftTest` hook internally. Query input + mode radio group + search button. Results rendered as cards with score, title, text (truncated), anchor metadata.

- [ ] **Step 3: Run tests, verify pass**

Run: `cd frontend && bunx vitest run src/tests/components/DraftTestPanel.test.tsx`

---

## Task 15: Frontend — SnapshotsTab (Wiring SnapshotCard + DraftTestPanel)

**Files:**

- Create: `frontend/src/pages/AdminPage/SnapshotsTab.tsx`
- Modify: `frontend/src/App.tsx` — replace placeholder with `<SnapshotsTab />`

- [ ] **Step 1: Implement SnapshotsTab**

Uses `useSnapshots` hook. Renders "+ New Draft" button (disabled if draft exists). Sorts snapshots: ACTIVE → DRAFT → PUBLISHED → ARCHIVED. Maps to SnapshotCard components. "Show archived" toggle at bottom. Test button on DRAFT card toggles DraftTestPanel visibility. Action handlers call hook methods + show toast on success/error.

- [ ] **Step 2: Update App.tsx route**

Replace `<div>Snapshots placeholder</div>` with `<SnapshotsTab />`.

- [ ] **Step 3: Consume ToastContext in SnapshotsTab**

`ToastContext` was already set up in AdminPage (Task 6). In SnapshotsTab, use `useContext(ToastContext)` to get `addToast` and call it on action success/error (e.g., `addToast("Published successfully", "success")`, `addToast(error.message, "error")`).

- [ ] **Step 4: Manual smoke test**

Run: `cd frontend && bun dev`
Navigate to `/admin/snapshots` — should show snapshot cards with action buttons.

---

## Task 16: Frontend — Full Integration Test & Cleanup

**Files:**

- Modify: `frontend/src/tests/integration/AdminPage.test.tsx`

- [ ] **Step 1: Expand admin integration tests**

Add test cases:

1. `/admin` redirects to `/admin/sources` when adminMode=true
2. `/admin` redirects to `/` when adminMode=false
3. Tab navigation between Sources and Snapshots works
4. Admin link visible in ChatHeader when adminMode=true

- [ ] **Step 2: Run full test suite**

Run: `cd frontend && bunx vitest run`
Expected: all tests pass (both new admin tests and existing chat tests)

- [ ] **Step 3: Run type check**

Run: `cd frontend && bunx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Run linter**

Run: `cd frontend && bunx biome check src/`
Expected: no errors (fix any issues)

- [ ] **Step 5: Run backend tests**

Run: `cd backend && python -m pytest --tb=short -q`
Expected: all pass

---

## Summary

| Task | Description                                                | Scope              |
| ---- | ---------------------------------------------------------- | ------------------ |
| 1    | Backend: GET /sources endpoint                             | Backend            |
| 2    | Backend: POST /snapshots endpoint                          | Backend            |
| 3    | Frontend: Admin TypeScript types                           | Frontend types     |
| 4    | Frontend: Admin API client + tests                         | Frontend API       |
| 5    | Frontend: UI primitives (badge, alert-dialog, toast, tabs) | Frontend UI        |
| 6    | Frontend: Admin routing & layout + ChatHeader link         | Frontend routing   |
| 7    | Frontend: useSources hook + tests                          | Frontend hook      |
| 8    | Frontend: useSnapshots hook + tests                        | Frontend hook      |
| 9    | Frontend: useDraftTest hook + tests                        | Frontend hook      |
| 10   | Frontend: DropZone component + tests                       | Frontend component |
| 11   | Frontend: SourceList component + tests                     | Frontend component |
| 12   | Frontend: SourcesTab wiring                                | Frontend page      |
| 13   | Frontend: SnapshotCard component + tests                   | Frontend component |
| 14   | Frontend: DraftTestPanel component + tests                 | Frontend component |
| 15   | Frontend: SnapshotsTab wiring + toast                      | Frontend page      |
| 16   | Frontend: Full integration test & cleanup                  | Frontend tests     |

**Parallelizable groups:**

- Tasks 1-2 (backend) can run in parallel with Tasks 3-5 (frontend types/API/primitives)
- Tasks 7-9 (hooks) can run in parallel after Task 4
- Tasks 10-11 (source components) can run in parallel with Tasks 13-14 (snapshot components) after Task 5
