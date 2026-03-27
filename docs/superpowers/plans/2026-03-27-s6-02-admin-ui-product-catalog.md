# S6-02: Admin UI — Product Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a product catalog management tab to the Admin UI so the agent owner can CRUD catalog items and link them to knowledge sources.

**Architecture:** New "Catalog" tab in Admin UI with table list, modal form dialog, and type filter dropdown. Monolithic `useCatalog` hook for state management (consistent with `useSources`/`useSnapshots` patterns). Source-catalog linking via dropdown in the Sources tab. All API calls go to the existing S6-01 backend endpoints.

**Tech Stack:** React 19, TypeScript, Radix UI Dialog, Tailwind CSS, i18next, Vite, Biome

**Spec:** `docs/superpowers/specs/2026-03-27-s6-02-admin-ui-product-catalog-design.md`

---

### Task 1: TypeScript types for catalog

**Files:**
- Modify: `frontend/src/types/admin.ts`

- [ ] **Step 1: Add catalog types to admin.ts**

First, update the existing `SourceListItem` interface to include `catalog_item_id` (the backend already returns this field):

```typescript
export interface SourceListItem {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
  description: string | null;
  public_url: string | null;
  file_size_bytes: number | null;
  language: string | null;
  catalog_item_id: string | null;
  created_at: string;
}
```

Then add the following types after the existing `DraftTestResponse` interface at the end of the file:

```typescript
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
  valid_from: string | null;
  valid_until: string | null;
  created_at: string;
  updated_at: string;
  linked_sources_count: number;
}

export interface LinkedSource {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
}

export interface CatalogItemDetail extends CatalogItem {
  linked_sources: LinkedSource[];
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

- [ ] **Step 2: Verify types compile**

Run: `cd frontend && bun run check`
Expected: no type errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/admin.ts
git commit -m "feat(catalog-ui): add TypeScript types for catalog items"
```

---

### Task 2: API client functions for catalog

**Files:**
- Modify: `frontend/src/lib/admin-api.ts`

- [ ] **Step 1: Add catalog API imports**

Add the new types to the import block at the top of `admin-api.ts`:

```typescript
import type {
  CatalogItem,
  CatalogItemCreate,
  CatalogItemDetail,
  CatalogItemListResponse,
  CatalogItemType,
  CatalogItemUpdate,
  DraftTestResponse,
  RetrievalMode,
  RollbackResponse,
  SnapshotResponse,
  SourceDeleteResponse,
  SourceListItem,
  SourceUpdateRequest,
  SourceUploadMetadata,
  SourceUploadResponse,
} from "@/types/admin";
```

- [ ] **Step 2: Add catalog CRUD functions**

Add these functions at the end of `admin-api.ts`:

```typescript
export async function getCatalogItems(
  itemType?: CatalogItemType,
): Promise<CatalogItemListResponse> {
  const params = new URLSearchParams();
  if (itemType) {
    params.set("item_type", itemType);
  }
  params.set("limit", "100");

  const query = params.toString();
  const response = await fetch(
    buildApiUrl(`/api/admin/catalog?${query}`),
    {
      method: "GET",
      headers: { Accept: "application/json" },
    },
  );

  return parseJsonResponse<CatalogItemListResponse>(response);
}

export async function getCatalogItem(
  catalogItemId: string,
): Promise<CatalogItemDetail> {
  const response = await fetch(
    buildApiUrl(
      `/api/admin/catalog/${encodeURIComponent(catalogItemId)}`,
    ),
    {
      method: "GET",
      headers: { Accept: "application/json" },
    },
  );

  return parseJsonResponse<CatalogItemDetail>(response);
}

export async function createCatalogItem(
  data: CatalogItemCreate,
): Promise<CatalogItem> {
  const response = await fetch(buildApiUrl("/api/admin/catalog"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(data),
  });

  return parseJsonResponse<CatalogItem>(response);
}

export async function updateCatalogItem(
  catalogItemId: string,
  data: CatalogItemUpdate,
): Promise<CatalogItem> {
  const response = await fetch(
    buildApiUrl(
      `/api/admin/catalog/${encodeURIComponent(catalogItemId)}`,
    ),
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(data),
    },
  );

  return parseJsonResponse<CatalogItem>(response);
}

export async function deleteCatalogItem(
  catalogItemId: string,
): Promise<CatalogItem> {
  const response = await fetch(
    buildApiUrl(
      `/api/admin/catalog/${encodeURIComponent(catalogItemId)}`,
    ),
    {
      method: "DELETE",
      headers: { Accept: "application/json" },
    },
  );

  return parseJsonResponse<CatalogItem>(response);
}

export async function updateSource(
  sourceId: string,
  data: SourceUpdateRequest,
): Promise<SourceListItem> {
  const response = await fetch(
    buildApiUrl(
      `/api/admin/sources/${encodeURIComponent(sourceId)}`,
    ),
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(data),
    },
  );

  return parseJsonResponse<SourceListItem>(response);
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd frontend && bun run check`
Expected: no type errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/admin-api.ts
git commit -m "feat(catalog-ui): add API client functions for catalog CRUD and source linking"
```

---

### Task 3: i18n — catalog translations

**Files:**
- Modify: `frontend/src/locales/en/admin.ts`

- [ ] **Step 1: Add catalog section to admin translations**

Add the `catalog` key after the `draftTest` section (before the closing `} as const`):

```typescript
  catalog: {
    tab: "Catalog",
    addProduct: "+ Add Product",
    filterAll: "All types",
    loading: "Loading catalog...",
    loadFailed: "Failed to load catalog",
    emptyState:
      "No products yet. Add a product to start building the catalog.",
    table: {
      name: "Name",
      sku: "SKU",
      type: "Type",
      sources: "Sources",
      actions: "Actions",
      linkedCount: "{{count}} linked",
      noLinks: "\u2014",
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
      created: 'Product "{{name}}" created',
      updated: 'Product "{{name}}" updated',
      deleted: 'Product "{{name}}" deleted',
      createFailed: "Failed to create product",
      updateFailed: "Failed to update product",
      deleteFailed: "Failed to delete product",
      skuConflict: "A product with this SKU already exists",
    },
    delete: {
      title: "Delete product {{name}}?",
      description:
        "This product will be deactivated and will no longer appear in citations or recommendations. Linked sources will retain their reference, but it will have no effect until the product is reactivated.",
      action: "Delete product",
    },
  },
  sourceLink: {
    label: "Link to product",
    placeholder: "Select a product...",
    noProducts: "No products available",
    noProductsHint: "Create products in the Catalog tab first.",
    unlink: "Unlink",
    unknownProduct: "unknown product",
  },
```

- [ ] **Step 2: Add translateCatalogItemType helper to i18n.ts**

Add this function after `translateSourceType` in `frontend/src/lib/i18n.ts`:

```typescript
export function translateCatalogItemType(itemType: CatalogItemType) {
  return translate(`admin.catalog.type.${itemType}`);
}
```

Also add `CatalogItemType` to the import:

```typescript
import type { CatalogItemType, SnapshotStatus, SourceStatus, SourceType } from "@/types/admin";
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && bun run check`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/locales/en/admin.ts frontend/src/lib/i18n.ts
git commit -m "feat(catalog-ui): add i18n translations for catalog tab"
```

---

### Task 4: `useCatalog` hook

**Files:**
- Create: `frontend/src/hooks/useCatalog.ts`

- [ ] **Step 1: Create the useCatalog hook**

Create `frontend/src/hooks/useCatalog.ts`:

```typescript
import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/hooks/useToast";
import {
  createCatalogItem,
  deleteCatalogItem,
  getCatalogItems,
  updateCatalogItem,
} from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { translate } from "@/lib/i18n";
import type {
  CatalogItem,
  CatalogItemCreate,
  CatalogItemType,
  CatalogItemUpdate,
} from "@/types/admin";

export function useCatalog() {
  const { pushToast } = useToast();
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filterType, setFilterType] = useState<CatalogItemType | null>(null);
  const [editingItem, setEditingItem] = useState<CatalogItem | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [deletingItemId, setDeletingItemId] = useState<string | null>(null);

  const loadItems = useCallback(
    async (type: CatalogItemType | null) => {
      try {
        const response = await getCatalogItems(type ?? undefined);
        setItems(response.items);
      } catch (error) {
        pushToast({
          message:
            error instanceof Error
              ? error.message
              : translate("admin.catalog.loadFailed"),
          tone: "error",
        });
      }
    },
    [pushToast],
  );

  useEffect(() => {
    let active = true;

    void (async () => {
      try {
        const response = await getCatalogItems(filterType ?? undefined);
        if (active) {
          setItems(response.items);
        }
      } catch (error) {
        if (active) {
          pushToast({
            message:
              error instanceof Error
                ? error.message
                : translate("admin.catalog.loadFailed"),
            tone: "error",
          });
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [filterType, pushToast]);

  const openCreate = useCallback(() => {
    setEditingItem(null);
    setIsDialogOpen(true);
  }, []);

  const openEdit = useCallback((item: CatalogItem) => {
    setEditingItem(item);
    setIsDialogOpen(true);
  }, []);

  const closeDialog = useCallback(() => {
    setIsDialogOpen(false);
    setEditingItem(null);
  }, []);

  const saveItem = useCallback(
    async (data: CatalogItemCreate | CatalogItemUpdate) => {
      setIsSaving(true);
      try {
        if (editingItem) {
          const updated = await updateCatalogItem(editingItem.id, data as CatalogItemUpdate);
          pushToast({
            message: translate("admin.catalog.toast.updated", {
              name: updated.name,
            }),
            tone: "success",
          });
        } else {
          const created = await createCatalogItem(data as CatalogItemCreate);
          pushToast({
            message: translate("admin.catalog.toast.created", {
              name: created.name,
            }),
            tone: "success",
          });
        }

        closeDialog();
        await loadItems(filterType);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          pushToast({
            message: translate("admin.catalog.toast.skuConflict"),
            tone: "error",
          });
        } else {
          pushToast({
            message:
              error instanceof Error
                ? error.message
                : translate(
                    editingItem
                      ? "admin.catalog.toast.updateFailed"
                      : "admin.catalog.toast.createFailed",
                  ),
            tone: "error",
          });
        }
      } finally {
        setIsSaving(false);
      }
    },
    [closeDialog, editingItem, filterType, loadItems, pushToast],
  );

  const removeItem = useCallback(
    async (item: CatalogItem) => {
      setDeletingItemId(item.id);
      try {
        await deleteCatalogItem(item.id);
        pushToast({
          message: translate("admin.catalog.toast.deleted", {
            name: item.name,
          }),
          tone: "success",
        });
        await loadItems(filterType);
      } catch (error) {
        pushToast({
          message:
            error instanceof Error
              ? error.message
              : translate("admin.catalog.toast.deleteFailed"),
          tone: "error",
        });
      } finally {
        setDeletingItemId(null);
      }
    },
    [filterType, loadItems, pushToast],
  );

  return {
    closeDialog,
    deletingItemId,
    editingItem,
    filterType,
    isDialogOpen,
    isLoading,
    isSaving,
    items,
    openCreate,
    openEdit,
    removeItem,
    saveItem,
    setFilterType,
  };
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd frontend && bun run check`
Expected: no type errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useCatalog.ts
git commit -m "feat(catalog-ui): add useCatalog hook for state management"
```

---

### Task 5: CatalogList component

**Files:**
- Create: `frontend/src/components/CatalogList/CatalogList.tsx`
- Create: `frontend/src/components/CatalogList/index.ts`

- [ ] **Step 1: Create the CatalogList component**

Create `frontend/src/components/CatalogList/CatalogList.tsx`:

```typescript
import { Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  AlertDialog,
  AlertDialogActionButton,
  AlertDialogCancelButton,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { translateCatalogItemType, useAppTranslation } from "@/lib/i18n";
import { formatRelativeTime } from "@/lib/strings";
import type { CatalogItem, CatalogItemType } from "@/types/admin";

function typeBadgeVariant(itemType: CatalogItemType) {
  switch (itemType) {
    case "book":
      return "info" as const;
    case "course":
      return "warning" as const;
    case "event":
      return "muted" as const;
    case "merch":
      return "success" as const;
    default:
      return "muted" as const;
  }
}

interface CatalogListProps {
  deletingItemId: string | null;
  items: CatalogItem[];
  onDelete: (item: CatalogItem) => void;
  onEdit: (item: CatalogItem) => void;
}

export function CatalogList({
  deletingItemId,
  items,
  onDelete,
  onEdit,
}: CatalogListProps) {
  const { t } = useAppTranslation();
  const [pendingItem, setPendingItem] = useState<CatalogItem | null>(null);

  if (items.length === 0) {
    return (
      <div className="rounded-[1.5rem] border border-dashed border-stone-300 bg-white/70 px-6 py-10 text-center text-sm text-stone-500">
        {t("admin.catalog.emptyState")}
      </div>
    );
  }

  return (
    <>
      <div className="hidden overflow-hidden rounded-[1.5rem] border border-white/70 bg-white/90 shadow-sm shadow-stone-900/5 md:block">
        <table className="min-w-full border-collapse">
          <thead className="bg-stone-100/80 text-left text-xs uppercase tracking-[0.16em] text-stone-500">
            <tr>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.name")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.sku")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.type")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.sources")}
              </th>
              <th className="px-5 py-4 font-medium text-right">
                {t("admin.catalog.table.actions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr className="border-t border-stone-200/80" key={item.id}>
                <td className="px-5 py-4 align-top">
                  <p className="m-0 font-medium text-stone-950">
                    {item.name}
                  </p>
                  {item.description ? (
                    <p className="m-0 mt-1 text-sm text-stone-500 line-clamp-1">
                      {item.description}
                    </p>
                  ) : null}
                </td>
                <td className="px-5 py-4 align-top font-mono text-sm text-stone-500">
                  {item.sku}
                </td>
                <td className="px-5 py-4 align-top">
                  <Badge variant={typeBadgeVariant(item.item_type)}>
                    {translateCatalogItemType(item.item_type)}
                  </Badge>
                </td>
                <td className="px-5 py-4 align-top text-sm text-stone-500">
                  {item.linked_sources_count > 0
                    ? t("admin.catalog.table.linkedCount", {
                        count: item.linked_sources_count,
                      })
                    : t("admin.catalog.table.noLinks")}
                </td>
                <td className="px-5 py-4 text-right align-top">
                  <div className="flex items-center justify-end gap-2">
                    <Button
                      aria-label={`Edit ${item.name}`}
                      onClick={() => onEdit(item)}
                      size="icon-sm"
                      type="button"
                      variant="outline"
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      aria-label={`Delete ${item.name}`}
                      disabled={deletingItemId === item.id}
                      onClick={() => setPendingItem(item)}
                      size="icon-sm"
                      type="button"
                      variant="outline"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-3 md:hidden">
        {items.map((item) => (
          <article
            className="rounded-[1.5rem] border border-white/70 bg-white/90 p-4 shadow-sm shadow-stone-900/5"
            key={item.id}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-2">
                <p className="m-0 font-medium text-stone-950">{item.name}</p>
                <p className="m-0 font-mono text-xs text-stone-500">
                  {item.sku}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Badge variant={typeBadgeVariant(item.item_type)}>
                    {translateCatalogItemType(item.item_type)}
                  </Badge>
                </div>
                <p className="m-0 text-sm text-stone-500">
                  {item.linked_sources_count > 0
                    ? t("admin.catalog.table.linkedCount", {
                        count: item.linked_sources_count,
                      })
                    : t("admin.catalog.table.noLinks")}
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  aria-label={`Edit ${item.name}`}
                  onClick={() => onEdit(item)}
                  size="icon-sm"
                  type="button"
                  variant="outline"
                >
                  <Pencil className="size-4" />
                </Button>
                <Button
                  aria-label={`Delete ${item.name}`}
                  disabled={deletingItemId === item.id}
                  onClick={() => setPendingItem(item)}
                  size="icon-sm"
                  type="button"
                  variant="outline"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </div>
          </article>
        ))}
      </div>

      <AlertDialog
        open={pendingItem !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingItem(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingItem
                ? t("admin.catalog.delete.title", { name: pendingItem.name })
                : undefined}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("admin.catalog.delete.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancelButton type="button">
              {t("common.cancel")}
            </AlertDialogCancelButton>
            <AlertDialogActionButton
              onClick={() => {
                if (pendingItem) {
                  onDelete(pendingItem);
                }
                setPendingItem(null);
              }}
              type="button"
              variant="destructive"
            >
              {t("admin.catalog.delete.action")}
            </AlertDialogActionButton>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
```

- [ ] **Step 2: Create index re-export**

Create `frontend/src/components/CatalogList/index.ts`:

```typescript
export { CatalogList } from "./CatalogList";
```

- [ ] **Step 3: Verify types compile**

Run: `cd frontend && bun run check`
Expected: no type errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/CatalogList/
git commit -m "feat(catalog-ui): add CatalogList table component"
```

---

### Task 6: CatalogFormDialog component

**Files:**
- Create: `frontend/src/components/CatalogFormDialog/CatalogFormDialog.tsx`
- Create: `frontend/src/components/CatalogFormDialog/index.ts`

- [ ] **Step 1: Create the CatalogFormDialog component**

Create `frontend/src/components/CatalogFormDialog/CatalogFormDialog.tsx`:

```typescript
import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getCatalogItem } from "@/lib/admin-api";
import {
  translateCatalogItemType,
  translateSourceStatus,
  translateSourceType,
  useAppTranslation,
} from "@/lib/i18n";
import type {
  CatalogItem,
  CatalogItemCreate,
  CatalogItemType,
  LinkedSource,
} from "@/types/admin";

const ITEM_TYPES: CatalogItemType[] = [
  "book",
  "course",
  "event",
  "merch",
  "other",
];

interface CatalogFormDialogProps {
  editingItem: CatalogItem | null;
  isSaving: boolean;
  onClose: () => void;
  onSave: (data: CatalogItemCreate) => void;
  open: boolean;
}

export function CatalogFormDialog({
  editingItem,
  isSaving,
  onClose,
  onSave,
  open,
}: CatalogFormDialogProps) {
  const { t } = useAppTranslation();
  const isEditMode = editingItem !== null;

  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [itemType, setItemType] = useState<CatalogItemType>("book");
  const [url, setUrl] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [linkedSources, setLinkedSources] = useState<LinkedSource[]>([]);
  const [isLoadingLinkedSources, setIsLoadingLinkedSources] = useState(false);
  const [linkedSourcesError, setLinkedSourcesError] = useState<string | null>(
    null,
  );

  useEffect(() => {
    if (!open) {
      return;
    }

    setLinkedSourcesError(null);
    let active = true;

    if (editingItem) {
      setSku(editingItem.sku);
      setName(editingItem.name);
      setDescription(editingItem.description ?? "");
      setItemType(editingItem.item_type);
      setUrl(editingItem.url ?? "");
      setImageUrl(editingItem.image_url ?? "");
      setValidFrom(editingItem.valid_from?.slice(0, 10) ?? "");
      setValidUntil(editingItem.valid_until?.slice(0, 10) ?? "");
      setLinkedSources([]);
      setIsLoadingLinkedSources(true);

      void (async () => {
        try {
          const detail = await getCatalogItem(editingItem.id);
          if (active) {
            setLinkedSources(detail.linked_sources);
          }
        } catch (error) {
          if (active) {
            setLinkedSources([]);
            setLinkedSourcesError(
              error instanceof Error
                ? error.message
                : t("admin.catalog.form.linkedSourcesLoadFailed"),
            );
          }
        } finally {
          if (active) {
            setIsLoadingLinkedSources(false);
          }
        }
      })();
    } else {
      setSku("");
      setName("");
      setDescription("");
      setItemType("book");
      setUrl("");
      setImageUrl("");
      setValidFrom("");
      setValidUntil("");
      setLinkedSources([]);
      setIsLoadingLinkedSources(false);
      setLinkedSourcesError(null);
    }

    return () => {
      active = false;
    };
  }, [open, editingItem, t]);

  const handleSubmit = () => {
    const data: CatalogItemCreate = {
      sku: sku.trim(),
      name: name.trim(),
      item_type: itemType,
      ...(description.trim() ? { description: description.trim() } : {}),
      ...(url.trim() ? { url: url.trim() } : {}),
      ...(imageUrl.trim() ? { image_url: imageUrl.trim() } : {}),
      ...(validFrom ? { valid_from: new Date(validFrom).toISOString() } : {}),
      ...(validUntil
        ? { valid_until: new Date(validUntil).toISOString() }
        : {}),
    };

    onSave(data);
  };

  const isValid = sku.trim().length > 0 && name.trim().length > 0;

  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-[1.5rem] border border-white/70 bg-white p-6 shadow-xl">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-semibold text-stone-950">
              {isEditMode
                ? t("admin.catalog.form.editTitle")
                : t("admin.catalog.form.createTitle")}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                aria-label="Close"
                className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
                type="button"
              >
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>

          <div className="mt-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-sku">
                  {t("admin.catalog.form.sku")} *
                </label>
                <input
                  className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none"
                  id="catalog-sku"
                  maxLength={64}
                  onChange={(e) => setSku(e.currentTarget.value)}
                  placeholder={t("admin.catalog.form.skuPlaceholder")}
                  type="text"
                  value={sku}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-type">
                  {t("admin.catalog.form.itemType")} *
                </label>
                <select
                  className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-stone-500 focus:outline-none"
                  id="catalog-type"
                  onChange={(e) => setItemType(e.currentTarget.value as CatalogItemType)}
                  value={itemType}
                >
                  {ITEM_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {translateCatalogItemType(type)}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-name">
                {t("admin.catalog.form.name")} *
              </label>
              <input
                className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none"
                id="catalog-name"
                maxLength={255}
                onChange={(e) => setName(e.currentTarget.value)}
                placeholder={t("admin.catalog.form.namePlaceholder")}
                type="text"
                value={name}
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-description">
                {t("admin.catalog.form.description")}
              </label>
              <textarea
                className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none"
                id="catalog-description"
                maxLength={2000}
                onChange={(e) => setDescription(e.currentTarget.value)}
                placeholder={t("admin.catalog.form.descriptionPlaceholder")}
                rows={3}
                value={description}
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-url">
                {t("admin.catalog.form.url")}
              </label>
              <input
                className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none"
                id="catalog-url"
                onChange={(e) => setUrl(e.currentTarget.value)}
                placeholder={t("admin.catalog.form.urlPlaceholder")}
                type="url"
                value={url}
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-image-url">
                {t("admin.catalog.form.imageUrl")}
              </label>
              <input
                className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none"
                id="catalog-image-url"
                onChange={(e) => setImageUrl(e.currentTarget.value)}
                placeholder={t("admin.catalog.form.imageUrlPlaceholder")}
                type="url"
                value={imageUrl}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-valid-from">
                  {t("admin.catalog.form.validFrom")}
                </label>
                <input
                  className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-stone-500 focus:outline-none"
                  id="catalog-valid-from"
                  onChange={(e) => setValidFrom(e.currentTarget.value)}
                  type="date"
                  value={validFrom}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="catalog-valid-until">
                  {t("admin.catalog.form.validUntil")}
                </label>
                <input
                  className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-stone-500 focus:outline-none"
                  id="catalog-valid-until"
                  min={validFrom || undefined}
                  onChange={(e) => setValidUntil(e.currentTarget.value)}
                  type="date"
                  value={validUntil}
                />
              </div>
            </div>

            {isEditMode && (
              <div className="border-t border-stone-200 pt-4">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-stone-500">
                  {t("admin.catalog.form.linkedSources")}
                </p>
                {linkedSources.length === 0 ? (
                  <p className="text-sm text-stone-400">
                    {t("admin.catalog.form.noLinkedSources")}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {linkedSources.map((source) => (
                      <div
                        className="flex items-center gap-2 text-sm text-stone-700"
                        key={source.id}
                      >
                        <span>{source.title}</span>
                        <Badge variant="muted">
                          {translateSourceType(source.source_type)}
                        </Badge>
                        <Badge variant="muted">
                          {translateSourceStatus(source.status)}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <Button onClick={onClose} type="button" variant="outline">
              {t("admin.catalog.form.cancel")}
            </Button>
            <Button
              disabled={!isValid || isSaving}
              onClick={handleSubmit}
              type="button"
            >
              {isEditMode
                ? t("admin.catalog.form.save")
                : t("admin.catalog.form.create")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
```

- [ ] **Step 2: Create index re-export**

Create `frontend/src/components/CatalogFormDialog/index.ts`:

```typescript
export { CatalogFormDialog } from "./CatalogFormDialog";
```

- [ ] **Step 3: Verify types compile**

Run: `cd frontend && bun run check`
Expected: no type errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/CatalogFormDialog/
git commit -m "feat(catalog-ui): add CatalogFormDialog modal component"
```

---

### Task 7: CatalogTab page and routing

**Files:**
- Create: `frontend/src/pages/AdminPage/CatalogTab.tsx`
- Modify: `frontend/src/pages/AdminPage/index.ts`
- Modify: `frontend/src/pages/AdminPage/AdminPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create CatalogTab page**

Create `frontend/src/pages/AdminPage/CatalogTab.tsx`:

```typescript
import { Plus } from "lucide-react";

import { CatalogFormDialog } from "@/components/CatalogFormDialog";
import { CatalogList } from "@/components/CatalogList";
import { Button } from "@/components/ui/button";
import { useCatalog } from "@/hooks/useCatalog";
import { translateCatalogItemType, useAppTranslation } from "@/lib/i18n";
import type { CatalogItemType } from "@/types/admin";

const ITEM_TYPES: CatalogItemType[] = [
  "book",
  "course",
  "event",
  "merch",
  "other",
];

export function CatalogTab() {
  const { t } = useAppTranslation();
  const {
    closeDialog,
    deletingItemId,
    editingItem,
    filterType,
    isDialogOpen,
    isLoading,
    isSaving,
    items,
    openCreate,
    openEdit,
    removeItem,
    saveItem,
    setFilterType,
  } = useCatalog();

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={openCreate} type="button">
          <Plus className="size-4" />
          {t("admin.catalog.addProduct")}
        </Button>

        <select
          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 focus:border-stone-500 focus:outline-none"
          onChange={(e) => {
            const value = e.currentTarget.value;
            setFilterType(value === "" ? null : (value as CatalogItemType));
          }}
          value={filterType ?? ""}
        >
          <option value="">{t("admin.catalog.filterAll")}</option>
          {ITEM_TYPES.map((type) => (
            <option key={type} value={type}>
              {translateCatalogItemType(type)}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="rounded-[1.5rem] border border-white/70 bg-white/90 px-6 py-8 text-sm text-stone-500 shadow-sm shadow-stone-900/5">
          {t("admin.catalog.loading")}
        </div>
      ) : (
        <CatalogList
          deletingItemId={deletingItemId}
          items={items}
          onDelete={(item) => {
            void removeItem(item);
          }}
          onEdit={openEdit}
        />
      )}

      <CatalogFormDialog
        editingItem={editingItem}
        isSaving={isSaving}
        onClose={closeDialog}
        onSave={(data) => {
          void saveItem(data);
        }}
        open={isDialogOpen}
      />
    </section>
  );
}
```

- [ ] **Step 2: Add CatalogTab to page re-exports**

In `frontend/src/pages/AdminPage/index.ts`, add the export:

```typescript
export { AdminPage } from "./AdminPage";
export { CatalogTab } from "./CatalogTab";
export { SnapshotsTab } from "./SnapshotsTab";
export { SourcesTab } from "./SourcesTab";
```

- [ ] **Step 3: Add Catalog tab to AdminPage navigation**

In `frontend/src/pages/AdminPage/AdminPage.tsx`, add the third tab inside `TabsList`:

```tsx
<TabsList aria-label={t("admin.sections")}>
  <TabsLink to="/admin/sources">{t("admin.tabs.sources")}</TabsLink>
  <TabsLink to="/admin/snapshots">
    {t("admin.tabs.snapshots")}
  </TabsLink>
  <TabsLink to="/admin/catalog">
    {t("admin.catalog.tab")}
  </TabsLink>
</TabsList>
```

- [ ] **Step 4: Add catalog route to App.tsx**

In `frontend/src/App.tsx`, add the import and route:

Update the import:
```typescript
import { AdminPage, CatalogTab, SnapshotsTab, SourcesTab } from "@/pages/AdminPage";
```

Add the route inside the `<Route element={<AdminPage />}>` block, after the snapshots route:
```tsx
<Route element={<CatalogTab />} path="catalog" />
```

- [ ] **Step 5: Verify the app builds**

Run: `cd frontend && bun run build`
Expected: build succeeds with no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AdminPage/CatalogTab.tsx frontend/src/pages/AdminPage/index.ts frontend/src/pages/AdminPage/AdminPage.tsx frontend/src/App.tsx
git commit -m "feat(catalog-ui): add CatalogTab page with routing and navigation"
```

---

### Task 8: Source-catalog linking in Sources tab

**Files:**
- Modify: `frontend/src/hooks/useSources.ts`
- Modify: `frontend/src/components/SourceList/SourceList.tsx`
- Modify: `frontend/src/pages/AdminPage/SourcesTab.tsx`

- [ ] **Step 1: Add catalog items loading to useSources**

In `frontend/src/hooks/useSources.ts`:

Add imports at top:
```typescript
import { getCatalogItems, updateSource } from "@/lib/admin-api";
import type { CatalogItem, SourceListItem } from "@/types/admin";
```

Add state inside `useSources()`:
```typescript
const [catalogItems, setCatalogItems] = useState<CatalogItem[]>([]);
```

Add catalog items fetch inside the existing initial load `useEffect` (after sources are loaded, within the same async block):
```typescript
try {
  const catalogResponse = await getCatalogItems();
  if (active) {
    setCatalogItems(catalogResponse.items);
  }
} catch {
  // Catalog items are optional for source management — ignore load failures
}
```

Add a `linkSourceToCatalog` callback:
```typescript
const linkSourceToCatalog = useCallback(
  async (sourceId: string, catalogItemId: string | null) => {
    try {
      await updateSource(sourceId, { catalog_item_id: catalogItemId });
      await refreshSources();
    } catch (error) {
      pushToast({
        message:
          error instanceof Error
            ? error.message
            : translate("admin.source.refreshFailed"),
        tone: "error",
      });
    }
  },
  [pushToast, refreshSources],
);
```

Add `catalogItems` and `linkSourceToCatalog` to the return object:
```typescript
return {
  catalogItems,
  deletingSourceId,
  isLoading,
  isUploading,
  linkSourceToCatalog,
  refreshSources,
  removeSource,
  sources,
  uploadFiles,
};
```

- [ ] **Step 2: Add Product column and linking to SourceList**

In `frontend/src/components/SourceList/SourceList.tsx`:

Update the props interface:
```typescript
interface SourceListProps {
  catalogItems: CatalogItem[];
  deletingSourceId: string | null;
  onDelete: (source: SourceListItem) => void;
  onLinkCatalog: (sourceId: string, catalogItemId: string | null) => void;
  sources: SourceListItem[];
}
```

Import `CatalogItem`:
```typescript
import type { CatalogItem, SourceListItem } from "@/types/admin";
```

Add a "Product" column header after "Status" in the desktop table:
```tsx
<th className="px-5 py-4 font-medium">
  {t("admin.sourceLink.label")}
</th>
```

Add a Product cell in each row (after the Status cell). Handle stale references: if a source has a `catalog_item_id` that isn't in the active catalog items list (e.g., the product was soft-deleted), show a fallback "(unknown product)" option so the admin can see and unlink it:
```tsx
<td className="px-5 py-4 align-top">
  <select
    className="w-full max-w-[180px] rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-sm text-stone-700 focus:border-stone-500 focus:outline-none"
    onChange={(e) => {
      const value = e.currentTarget.value;
      onLinkCatalog(source.id, value === "" ? null : value);
    }}
    value={source.catalog_item_id ?? ""}
  >
    <option value="">{t("admin.sourceLink.placeholder")}</option>
    {source.catalog_item_id &&
      !catalogItems.some((item) => item.id === source.catalog_item_id) && (
      <option disabled value={source.catalog_item_id}>
        ({t("admin.sourceLink.unknownProduct")})
      </option>
    )}
    {catalogItems.map((item) => (
      <option key={item.id} value={item.id}>
        {item.name} ({item.sku})
      </option>
    ))}
  </select>
</td>
```

Note: `SourceListItem.catalog_item_id` was already added to the frontend type in Task 1. The backend `SourceListItem` schema (`source_schemas.py`) already returns this field.

- [ ] **Step 3: Update SourcesTab to pass new props**

In `frontend/src/pages/AdminPage/SourcesTab.tsx`:

```typescript
const {
  catalogItems,
  deletingSourceId,
  isLoading,
  isUploading,
  linkSourceToCatalog,
  removeSource,
  sources,
  uploadFiles,
} = useSources();
```

Update the JSX. The "Link to product" dropdown for uploads is placed **outside the DropZone** as a sibling element, not inside it (DropZone is a single clickable/droppable area — embedding controls inside causes event conflicts). Use a state variable to hold the selected catalog item for uploads:

```tsx
export function SourcesTab() {
  const { t } = useAppTranslation();
  const {
    catalogItems,
    deletingSourceId,
    isLoading,
    isUploading,
    linkSourceToCatalog,
    removeSource,
    sources,
    uploadFiles,
  } = useSources();

  const [uploadCatalogItemId, setUploadCatalogItemId] = useState<string | null>(null);

  return (
    <section className="space-y-5">
      <DropZone
        disabled={isUploading}
        isUploading={isUploading}
        onFiles={(files) => {
          void uploadFiles(files, uploadCatalogItemId);
        }}
      />

      {catalogItems.length > 0 && (
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium uppercase tracking-wider text-stone-500" htmlFor="upload-catalog-link">
            {t("admin.sourceLink.label")}
          </label>
          <select
            className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 focus:border-stone-500 focus:outline-none"
            id="upload-catalog-link"
            onChange={(e) => setUploadCatalogItemId(e.currentTarget.value || null)}
            value={uploadCatalogItemId ?? ""}
          >
            <option value="">{t("admin.sourceLink.placeholder")}</option>
            {catalogItems.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.sku})
              </option>
            ))}
          </select>
        </div>
      )}

      {isLoading ? (
        <div className="rounded-[1.5rem] border border-white/70 bg-white/90 px-6 py-8 text-sm text-stone-500 shadow-sm shadow-stone-900/5">
          {t("admin.loading.sources")}
        </div>
      ) : (
        <SourceList
          catalogItems={catalogItems}
          deletingSourceId={deletingSourceId}
          onDelete={(source) => {
            void removeSource(source);
          }}
          onLinkCatalog={(sourceId, catalogItemId) => {
            void linkSourceToCatalog(sourceId, catalogItemId);
          }}
          sources={sources}
        />
      )}
    </section>
  );
}
```

Note: `uploadFiles` needs to accept an optional `catalogItemId` parameter. Update the `useSources` hook's `uploadFiles` function to accept and pass `catalogItemId` in the `SourceUploadMetadata`:

```typescript
const uploadFiles = useCallback(
  async (files: File[], catalogItemId?: string | null) => {
    // ... existing validation ...
    const results = await Promise.allSettled(
      validFiles.map((file) =>
        uploadSource(file, {
          title: deriveSourceTitle(file.name),
          ...(catalogItemId ? { catalog_item_id: catalogItemId } : {}),
        }),
      ),
    );
    // ... rest unchanged ...
  },
  [pushToast, refreshSources],
);
```

- [ ] **Step 4: Verify the app builds**

Run: `cd frontend && bun run build`
Expected: build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSources.ts frontend/src/components/SourceList/SourceList.tsx frontend/src/pages/AdminPage/SourcesTab.tsx
git commit -m "feat(catalog-ui): add source-catalog linking in Sources tab"
```

---

### Task 9: Lint, build, and manual verification

**Files:** none (verification only)

- [ ] **Step 1: Run Biome lint**

Run: `cd frontend && bunx biome check --write .`
Expected: no errors (warnings ok, auto-fixed)

- [ ] **Step 2: Run type check**

Run: `cd frontend && bun run check`
Expected: no type errors

- [ ] **Step 3: Run build**

Run: `cd frontend && bun run build`
Expected: build succeeds

- [ ] **Step 4: Fix any lint/type/build issues**

If any issues found in steps 1-3, fix them and re-run.

- [ ] **Step 5: Manual smoke test**

Start the dev server and verify manually:
1. Navigate to `/admin` — three tabs visible (Sources, Snapshots, Catalog)
2. Click Catalog tab — empty state shown
3. Click "+ Add Product" — form dialog opens with all 8 fields
4. Create a product (fill sku, name, type) — toast success, item appears in table
5. Click edit icon — dialog opens pre-filled, linked sources section visible
6. Click delete icon — confirmation dialog with warning text
7. Use type filter dropdown — list filters correctly
8. Go to Sources tab — "Product" column visible with dropdown
9. Select a product from dropdown — source links to catalog item

Run: `cd frontend && bun dev`

- [ ] **Step 6: Final commit if any fixes were made**

```bash
git add -A
git commit -m "fix(catalog-ui): lint and build fixes"
```
