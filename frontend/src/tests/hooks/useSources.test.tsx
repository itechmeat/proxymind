import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSources } from "@/hooks/useSources";
import { ToastProvider, useToast } from "@/hooks/useToast";
import * as adminApi from "@/lib/admin-api";
import { translate } from "@/lib/i18n";

vi.mock("@/lib/admin-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/admin-api")>("@/lib/admin-api");

  return {
    ...actual,
    deleteSource: vi.fn(),
    getCatalogItems: vi.fn(),
    getSources: vi.fn(),
    updateSource: vi.fn(),
    uploadSource: vi.fn(),
  };
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}

describe("useSources", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.mocked(adminApi.getCatalogItems).mockReset();
    vi.mocked(adminApi.getSources).mockReset();
    vi.mocked(adminApi.updateSource).mockReset();
    vi.mocked(adminApi.uploadSource).mockReset();
    vi.mocked(adminApi.deleteSource).mockReset();
  });

  it("polls while sources are processing", async () => {
    vi.useFakeTimers();
    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([
        {
          id: "source-1",
          catalog_item_id: null,
          title: "Doc",
          source_type: "pdf",
          status: "processing",
          description: null,
          public_url: null,
          file_size_bytes: null,
          language: null,
          created_at: "2026-03-25T12:00:00Z",
        },
      ])
      .mockResolvedValueOnce([]);

    renderHook(() => useSources(), { wrapper });

    await act(async () => {
      await Promise.resolve();
    });

    expect(adminApi.getSources).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(adminApi.getSources).toHaveBeenCalledTimes(2);
  });

  it("refreshes catalog items on the configured polling interval", async () => {
    vi.useFakeTimers();
    vi.mocked(adminApi.getCatalogItems)
      .mockResolvedValueOnce({
        items: [],
        total: 0,
      })
      .mockResolvedValueOnce({
        items: [
          {
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
          },
        ],
        total: 1,
      });
    vi.mocked(adminApi.getSources).mockResolvedValue([]);

    const { result } = renderHook(
      () => useSources({ catalogRefreshIntervalMs: 1000 }),
      { wrapper },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      await Promise.resolve();
    });

    expect(adminApi.getCatalogItems).toHaveBeenCalledTimes(2);
    expect(result.current.catalogItems[0]?.id).toBe("catalog-1");
  });

  it("rejects invalid files before upload", async () => {
    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources).mockResolvedValue([]);

    const { result } = renderHook(() => useSources(), { wrapper });

    await waitFor(() => {
      expect(adminApi.getSources).toHaveBeenCalled();
    });

    await act(async () => {
      await result.current.uploadFiles([new File(["x"], "table.xlsx")]);
    });

    expect(adminApi.uploadSource).not.toHaveBeenCalled();
  });

  it("rejects empty files before upload", async () => {
    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources).mockResolvedValue([]);

    const { result } = renderHook(() => useSources(), { wrapper });

    await waitFor(() => {
      expect(adminApi.getSources).toHaveBeenCalled();
    });

    await act(async () => {
      await result.current.uploadFiles([new File([], "empty.md")]);
    });

    expect(adminApi.uploadSource).not.toHaveBeenCalled();
  });

  it("uploads valid files and refreshes sources", async () => {
    const uploadedSource = {
      id: "source-1",
      catalog_item_id: null,
      title: "notes",
      source_type: "markdown",
      status: "pending",
      description: null,
      public_url: null,
      file_size_bytes: null,
      language: null,
      created_at: "2026-03-25T12:00:00Z",
    } as const;

    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([uploadedSource]);
    vi.mocked(adminApi.uploadSource).mockResolvedValue({
      source_id: "source-1",
      task_id: "task-1",
      status: "pending",
      file_path: "sources/notes.md",
      message: "queued",
    });

    const { result } = renderHook(() => useSources(), { wrapper });

    await waitFor(() => {
      expect(adminApi.getSources).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      await result.current.uploadFiles([new File(["hello"], "notes.md")]);
    });

    expect(adminApi.uploadSource).toHaveBeenCalledTimes(1);
    expect(adminApi.getSources).toHaveBeenCalledTimes(2);
    expect(result.current.sources).toEqual([uploadedSource]);
  });

  it("keeps successful uploads successful when the refresh fails", async () => {
    const refreshFailed = translate("admin.source.refreshFailed");

    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error(refreshFailed));
    vi.mocked(adminApi.uploadSource).mockResolvedValue({
      source_id: "source-1",
      task_id: "task-1",
      status: "pending",
      file_path: "sources/notes.md",
      message: "queued",
    });

    const { result } = renderHook(
      () => {
        const sources = useSources();
        const toast = useToast();

        return {
          ...sources,
          toasts: toast.toasts,
        };
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.uploadFiles([new File(["hello"], "notes.md")]);
    });

    expect(adminApi.uploadSource).toHaveBeenCalledTimes(1);
    expect(result.current.isUploading).toBe(false);
    expect(result.current.toasts.map((toast) => toast.message)).toEqual(
      expect.arrayContaining([
        translate("admin.source.queuedForIngestion", { filename: "notes.md" }),
        refreshFailed,
      ]),
    );
  });

  it("deletes a source and refreshes the list", async () => {
    const source = {
      id: "source-1",
      catalog_item_id: null,
      title: "Doc",
      source_type: "pdf",
      status: "ready",
      description: null,
      public_url: null,
      file_size_bytes: null,
      language: null,
      created_at: "2026-03-25T12:00:00Z",
    } as const;

    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([source])
      .mockResolvedValueOnce([]);
    vi.mocked(adminApi.deleteSource).mockResolvedValue({
      id: "source-1",
      title: "Doc",
      source_type: "pdf",
      status: "deleted",
      deleted_at: "2026-03-25T12:01:00Z",
      warnings: [],
    });

    const { result } = renderHook(() => useSources(), { wrapper });

    await waitFor(() => {
      expect(result.current.sources).toHaveLength(1);
    });

    await act(async () => {
      await result.current.removeSource(source);
    });

    expect(adminApi.deleteSource).toHaveBeenCalledWith("source-1");
    expect(adminApi.getSources).toHaveBeenCalledTimes(2);
  });

  it("links a source to a catalog item and refreshes sources", async () => {
    const source = {
      id: "source-1",
      catalog_item_id: null,
      title: "Doc",
      source_type: "pdf",
      status: "ready",
      description: null,
      public_url: null,
      file_size_bytes: null,
      language: null,
      created_at: "2026-03-25T12:00:00Z",
    } as const;

    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [
        {
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
        },
      ],
      total: 1,
    });
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([source])
      .mockResolvedValueOnce([
        {
          ...source,
          catalog_item_id: "catalog-1",
        },
      ]);
    vi.mocked(adminApi.updateSource).mockResolvedValue({
      ...source,
      catalog_item_id: "catalog-1",
    });

    const { result } = renderHook(() => useSources(), { wrapper });

    await waitFor(() => {
      expect(result.current.sources).toHaveLength(1);
    });

    await act(async () => {
      await result.current.linkSourceToCatalog("source-1", "catalog-1");
    });

    expect(adminApi.updateSource).toHaveBeenCalledWith("source-1", {
      catalog_item_id: "catalog-1",
    });
    expect(adminApi.getSources).toHaveBeenCalledTimes(2);
  });

  it("surfaces catalog load failures and supports manual retry", async () => {
    vi.mocked(adminApi.getCatalogItems)
      .mockRejectedValueOnce(new Error("Failed to load products"))
      .mockResolvedValueOnce({
        items: [
          {
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
          },
        ],
        total: 1,
      });
    vi.mocked(adminApi.getSources).mockResolvedValue([]);

    const { result } = renderHook(() => useSources(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.catalogLoadError).toBe("Failed to load products");
    expect(result.current.catalogItems).toEqual([]);

    await act(async () => {
      await result.current.refreshCatalogItems();
    });

    expect(result.current.catalogLoadError).toBeNull();
    expect(result.current.catalogItems[0]?.id).toBe("catalog-1");
  });

  it("refreshes catalog items when the window regains focus", async () => {
    vi.mocked(adminApi.getCatalogItems)
      .mockResolvedValueOnce({
        items: [],
        total: 0,
      })
      .mockResolvedValueOnce({
        items: [
          {
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
          },
        ],
        total: 1,
      });
    vi.mocked(adminApi.getSources).mockResolvedValue([]);

    const { result } = renderHook(() => useSources(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => {
      expect(adminApi.getCatalogItems).toHaveBeenCalledTimes(2);
    });

    await waitFor(() => {
      expect(result.current.catalogItems[0]?.id).toBe("catalog-1");
    });
  });

  it("keeps an updated source visible when refresh fails after linking", async () => {
    const source = {
      id: "source-1",
      catalog_item_id: null,
      title: "Doc",
      source_type: "pdf",
      status: "ready",
      description: null,
      public_url: null,
      file_size_bytes: null,
      language: null,
      created_at: "2026-03-25T12:00:00Z",
    } as const;
    const refreshFailed = translate("admin.source.refreshFailed");

    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([source])
      .mockRejectedValueOnce(new Error(refreshFailed));
    vi.mocked(adminApi.updateSource).mockResolvedValue({
      ...source,
      catalog_item_id: "catalog-1",
    });

    const { result } = renderHook(
      () => {
        const sources = useSources();
        const toast = useToast();

        return {
          ...sources,
          toasts: toast.toasts,
        };
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.sources).toHaveLength(1);
    });

    await act(async () => {
      await result.current.linkSourceToCatalog("source-1", "catalog-1");
    });

    expect(result.current.sources[0]?.catalog_item_id).toBe("catalog-1");
    expect(result.current.toasts.map((toast) => toast.message)).toEqual(
      expect.arrayContaining([refreshFailed]),
    );
  });

  it("keeps a deleted source removed when refresh fails after deletion", async () => {
    const source = {
      id: "source-1",
      catalog_item_id: null,
      title: "Doc",
      source_type: "pdf",
      status: "ready",
      description: null,
      public_url: null,
      file_size_bytes: null,
      language: null,
      created_at: "2026-03-25T12:00:00Z",
    } as const;
    const refreshFailed = translate("admin.source.refreshFailed");

    vi.mocked(adminApi.getCatalogItems).mockResolvedValue({
      items: [],
      total: 0,
    });
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([source])
      .mockRejectedValueOnce(new Error(refreshFailed));
    vi.mocked(adminApi.deleteSource).mockResolvedValue({
      id: "source-1",
      title: "Doc",
      source_type: "pdf",
      status: "deleted",
      deleted_at: "2026-03-25T12:01:00Z",
      warnings: [],
    });

    const { result } = renderHook(
      () => {
        const sources = useSources();
        const toast = useToast();

        return {
          ...sources,
          toasts: toast.toasts,
        };
      },
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.sources).toHaveLength(1);
    });

    await act(async () => {
      await result.current.removeSource(source);
    });

    expect(result.current.sources).toEqual([]);
    expect(result.current.toasts.map((toast) => toast.message)).toEqual(
      expect.arrayContaining([
        translate("admin.source.deleted", { title: "Doc" }),
        refreshFailed,
      ]),
    );
  });
});
