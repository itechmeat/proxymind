import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDraftTest } from "@/hooks/useDraftTest";
import { ToastProvider, useToast } from "@/hooks/useToast";
import * as adminApi from "@/lib/admin-api";
import { translate } from "@/lib/i18n";

vi.mock("@/lib/admin-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/admin-api")>("@/lib/admin-api");

  return {
    ...actual,
    testDraftSnapshot: vi.fn(),
  };
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}

describe("useDraftTest", () => {
  beforeEach(() => {
    vi.mocked(adminApi.testDraftSnapshot).mockReset();
  });

  it("stores draft test results", async () => {
    vi.mocked(adminApi.testDraftSnapshot).mockResolvedValue({
      snapshot_id: "draft-1",
      snapshot_name: "Draft",
      query: "what changed",
      mode: "hybrid",
      total_chunks_in_draft: 3,
      results: [],
    });

    const { result } = renderHook(() => useDraftTest(), { wrapper });

    await act(async () => {
      await result.current.runDraftTest({
        mode: "hybrid",
        query: "what changed",
        snapshotId: "draft-1",
      });
    });

    expect(result.current.result?.snapshot_id).toBe("draft-1");
  });

  it("rethrows errors, pushes a toast, and clears loading state", async () => {
    const failureMessage = translate("admin.draftTest.failed");

    vi.mocked(adminApi.testDraftSnapshot).mockRejectedValue(
      new Error(failureMessage),
    );

    const { result } = renderHook(
      () => {
        const draftTest = useDraftTest();
        const toast = useToast();

        return {
          ...draftTest,
          toasts: toast.toasts,
        };
      },
      { wrapper },
    );

    await act(async () => {
      await expect(
        result.current.runDraftTest({
          mode: "hybrid",
          query: "what changed",
          snapshotId: "draft-1",
        }),
      ).rejects.toThrow(failureMessage);
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.toasts.at(-1)?.message).toBe(failureMessage);
      expect(result.current.toasts.at(-1)?.tone).toBe("error");
    });
  });
});
