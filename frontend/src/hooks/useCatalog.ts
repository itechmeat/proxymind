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
    async (type: CatalogItemType | null, keepLoadingState = false) => {
      if (!keepLoadingState) {
        setIsLoading(true);
      }

      try {
        const response = await getCatalogItems(type ?? undefined);
        setItems(response.items);
        return response.items;
      } catch (error) {
        pushToast({
          message:
            error instanceof Error
              ? error.message
              : translate("admin.catalog.loadFailed"),
          tone: "error",
        });
        return null;
      } finally {
        if (!keepLoadingState) {
          setIsLoading(false);
        }
      }
    },
    [pushToast],
  );

  useEffect(() => {
    let active = true;

    void (async () => {
      setIsLoading(true);
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
          const updated = await updateCatalogItem(editingItem.id, data);
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
        await loadItems(filterType, true);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          pushToast({
            message: translate("admin.catalog.toast.skuConflict"),
            tone: "error",
          });
          await loadItems(filterType, true);
          return;
        }

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
        await loadItems(filterType, true);
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
