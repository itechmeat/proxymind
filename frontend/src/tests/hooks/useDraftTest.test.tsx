import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useDraftTest } from "@/hooks/useDraftTest";
import { ToastProvider } from "@/hooks/useToast";
import * as adminApi from "@/lib/admin-api";

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
});
