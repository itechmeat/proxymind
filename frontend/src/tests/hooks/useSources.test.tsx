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
    getSources: vi.fn(),
    uploadSource: vi.fn(),
  };
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}

describe("useSources", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.mocked(adminApi.getSources).mockReset();
    vi.mocked(adminApi.uploadSource).mockReset();
    vi.mocked(adminApi.deleteSource).mockReset();
  });

  it("polls while sources are processing", async () => {
    vi.useFakeTimers();
    vi.mocked(adminApi.getSources)
      .mockResolvedValueOnce([
        {
          id: "source-1",
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

  it("rejects invalid files before upload", async () => {
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
      title: "notes",
      source_type: "markdown",
      status: "pending",
      description: null,
      public_url: null,
      file_size_bytes: null,
      language: null,
      created_at: "2026-03-25T12:00:00Z",
    } as const;

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
      title: "Doc",
      source_type: "pdf",
      status: "ready",
      description: null,
      public_url: null,
      file_size_bytes: null,
      language: null,
      created_at: "2026-03-25T12:00:00Z",
    } as const;

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
});
