import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCatalog } from "@/hooks/useCatalog";
import { ToastProvider, useToast } from "@/hooks/useToast";
import * as adminApi from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { translate } from "@/lib/i18n";

vi.mock("@/lib/admin-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/admin-api")>("@/lib/admin-api");

  return {
    ...actual,
    createCatalogItem: vi.fn(),
    deleteCatalogItem: vi.fn(),
    getCatalogItems: vi.fn(),
    updateCatalogItem: vi.fn(),
  };
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}

const catalogItem = {
  id: "catalog-1",
  sku: "BOOK-001",
  name: "AI in Practice",
  description: null,
  item_type: "book",
  url: null,
  image_url: null,
  is_active: true,
  valid_from: null,
  valid_until: null,
  created_at: "2026-03-25T12:00:00Z",
  updated_at: "2026-03-25T12:00:00Z",
  linked_sources_count: 0,
} as const;

describe("useCatalog", () => {
  beforeEach(() => {
    vi.mocked(adminApi.createCatalogItem).mockReset();
    vi.mocked(adminApi.deleteCatalogItem).mockReset();
    vi.mocked(adminApi.getCatalogItems).mockReset();
    vi.mocked(adminApi.updateCatalogItem).mockReset();
  });

  it("loads catalog items and filters them", async () => {
    vi.mocked(adminApi.getCatalogItems)
      .mockResolvedValueOnce({ items: [catalogItem], total: 1 })
      .mockResolvedValueOnce({ items: [catalogItem], total: 1 });

    const { result } = renderHook(() => useCatalog(), { wrapper });

    await waitFor(() => {
      expect(result.current.items).toHaveLength(1);
    });

    await act(async () => {
      result.current.setFilterType("book");
    });

    await waitFor(() => {
      expect(adminApi.getCatalogItems).toHaveBeenLastCalledWith("book");
    });
  });

  it("creates a catalog item and shows success toast", async () => {
    vi.mocked(adminApi.getCatalogItems)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [catalogItem], total: 1 });
    vi.mocked(adminApi.createCatalogItem).mockResolvedValue(catalogItem);

    const { result } = renderHook(
      () => {
        const catalog = useCatalog();
        const toast = useToast();

        return { ...catalog, toasts: toast.toasts };
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.saveItem({
        sku: "BOOK-001",
        name: "AI in Practice",
        item_type: "book",
      });
    });

    expect(adminApi.createCatalogItem).toHaveBeenCalled();
    expect(result.current.toasts.map((toast) => toast.message)).toEqual(
      expect.arrayContaining([
        translate("admin.catalog.toast.created", { name: "AI in Practice" }),
      ]),
    );
  });

  it("surfaces SKU conflict toast on 409", async () => {
    vi.mocked(adminApi.getCatalogItems)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [], total: 0 });
    vi.mocked(adminApi.createCatalogItem).mockRejectedValue(
      new ApiError(409, "conflict"),
    );

    const { result } = renderHook(
      () => {
        const catalog = useCatalog();
        const toast = useToast();

        return { ...catalog, toasts: toast.toasts };
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.saveItem({
        sku: "BOOK-001",
        name: "AI in Practice",
        item_type: "book",
      });
    });

    expect(result.current.toasts.map((toast) => toast.message)).toEqual(
      expect.arrayContaining([translate("admin.catalog.toast.skuConflict")]),
    );
  });

  it("updates an existing catalog item and shows success toast", async () => {
    const updatedItem = {
      ...catalogItem,
      name: "AI in Practice 2nd Ed",
      updated_at: "2026-03-25T12:05:00Z",
    } as const;

    vi.mocked(adminApi.getCatalogItems)
      .mockResolvedValueOnce({ items: [catalogItem], total: 1 })
      .mockResolvedValueOnce({ items: [updatedItem], total: 1 });
    vi.mocked(adminApi.updateCatalogItem).mockResolvedValue(updatedItem);

    const { result } = renderHook(
      () => {
        const catalog = useCatalog();
        const toast = useToast();

        return { ...catalog, toasts: toast.toasts };
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.items).toHaveLength(1);
    });

    act(() => {
      result.current.openEdit(catalogItem);
    });

    await act(async () => {
      await result.current.saveItem({ name: "AI in Practice 2nd Ed" });
    });

    expect(adminApi.updateCatalogItem).toHaveBeenCalledWith("catalog-1", {
      name: "AI in Practice 2nd Ed",
    });
    expect(result.current.toasts.map((toast) => toast.message)).toEqual(
      expect.arrayContaining([
        translate("admin.catalog.toast.updated", {
          name: "AI in Practice 2nd Ed",
        }),
      ]),
    );
  });

  it("deletes a catalog item and refreshes the list", async () => {
    vi.mocked(adminApi.getCatalogItems)
      .mockResolvedValueOnce({ items: [catalogItem], total: 1 })
      .mockResolvedValueOnce({ items: [], total: 0 });
    vi.mocked(adminApi.deleteCatalogItem).mockResolvedValue({
      ...catalogItem,
      is_active: false,
      updated_at: "2026-03-25T12:10:00Z",
    });

    const { result } = renderHook(
      () => {
        const catalog = useCatalog();
        const toast = useToast();

        return { ...catalog, toasts: toast.toasts };
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.items).toHaveLength(1);
    });

    await act(async () => {
      await result.current.removeItem(catalogItem);
    });

    expect(adminApi.deleteCatalogItem).toHaveBeenCalledWith("catalog-1");
    await waitFor(() => {
      expect(result.current.items).toEqual([]);
    });
    expect(result.current.toasts.map((toast) => toast.message)).toEqual(
      expect.arrayContaining([
        translate("admin.catalog.toast.deleted", { name: "AI in Practice" }),
      ]),
    );
  });
});
