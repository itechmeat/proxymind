import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSnapshots } from "@/hooks/useSnapshots";
import { ToastProvider } from "@/hooks/useToast";
import * as adminApi from "@/lib/admin-api";

vi.mock("@/lib/admin-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/admin-api")>("@/lib/admin-api");

  return {
    ...actual,
    activateSnapshot: vi.fn(),
    createSnapshot: vi.fn(),
    getSnapshots: vi.fn(),
    publishSnapshot: vi.fn(),
    rollbackSnapshot: vi.fn(),
  };
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}

describe("useSnapshots", () => {
  beforeEach(() => {
    vi.mocked(adminApi.activateSnapshot).mockReset();
    vi.mocked(adminApi.createSnapshot).mockReset();
    vi.mocked(adminApi.getSnapshots).mockReset();
    vi.mocked(adminApi.publishSnapshot).mockReset();
    vi.mocked(adminApi.rollbackSnapshot).mockReset();
  });

  it("sorts snapshots by status priority", async () => {
    vi.mocked(adminApi.getSnapshots).mockResolvedValue([
      {
        id: "published-1",
        agent_id: null,
        knowledge_base_id: null,
        name: "Published",
        description: null,
        status: "published",
        published_at: null,
        activated_at: null,
        archived_at: null,
        chunk_count: 1,
        created_at: "2026-03-25T12:00:00Z",
        updated_at: "2026-03-25T12:00:00Z",
      },
      {
        id: "active-1",
        agent_id: null,
        knowledge_base_id: null,
        name: "Active",
        description: null,
        status: "active",
        published_at: null,
        activated_at: null,
        archived_at: null,
        chunk_count: 2,
        created_at: "2026-03-25T13:00:00Z",
        updated_at: "2026-03-25T13:00:00Z",
      },
    ]);

    const { result } = renderHook(() => useSnapshots(), { wrapper });

    await waitFor(() => {
      expect(result.current.snapshots[0]?.id).toBe("active-1");
    });
  });

  it("creates a draft and refreshes snapshots", async () => {
    vi.mocked(adminApi.getSnapshots)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          id: "draft-1",
          agent_id: null,
          knowledge_base_id: null,
          name: "Draft",
          description: null,
          status: "draft",
          published_at: null,
          activated_at: null,
          archived_at: null,
          chunk_count: 0,
          created_at: "2026-03-25T12:00:00Z",
          updated_at: "2026-03-25T12:00:00Z",
        },
      ]);
    vi.mocked(adminApi.createSnapshot).mockResolvedValue({
      id: "draft-1",
      agent_id: null,
      knowledge_base_id: null,
      name: "Draft",
      description: null,
      status: "draft",
      published_at: null,
      activated_at: null,
      archived_at: null,
      chunk_count: 0,
      created_at: "2026-03-25T12:00:00Z",
      updated_at: "2026-03-25T12:00:00Z",
    });

    const { result } = renderHook(() => useSnapshots(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.createDraft();
    });

    expect(adminApi.createSnapshot).toHaveBeenCalled();
    expect(result.current.draftSnapshot?.id).toBe("draft-1");
  });

  it("runs publish, activate, and rollback mutations", async () => {
    vi.mocked(adminApi.getSnapshots)
      .mockResolvedValueOnce([
        {
          id: "draft-1",
          agent_id: null,
          knowledge_base_id: null,
          name: "Draft",
          description: null,
          status: "draft",
          published_at: null,
          activated_at: null,
          archived_at: null,
          chunk_count: 0,
          created_at: "2026-03-25T12:00:00Z",
          updated_at: "2026-03-25T12:00:00Z",
        },
      ])
      .mockResolvedValue([
        {
          id: "published-1",
          agent_id: null,
          knowledge_base_id: null,
          name: "Published",
          description: null,
          status: "published",
          published_at: null,
          activated_at: null,
          archived_at: null,
          chunk_count: 1,
          created_at: "2026-03-25T12:00:00Z",
          updated_at: "2026-03-25T12:00:00Z",
        },
      ]);
    vi.mocked(adminApi.publishSnapshot).mockResolvedValue({
      id: "published-1",
      agent_id: null,
      knowledge_base_id: null,
      name: "Published",
      description: null,
      status: "published",
      published_at: null,
      activated_at: null,
      archived_at: null,
      chunk_count: 1,
      created_at: "2026-03-25T12:00:00Z",
      updated_at: "2026-03-25T12:00:00Z",
    });
    vi.mocked(adminApi.activateSnapshot).mockResolvedValue({
      id: "active-1",
      agent_id: null,
      knowledge_base_id: null,
      name: "Active",
      description: null,
      status: "active",
      published_at: null,
      activated_at: null,
      archived_at: null,
      chunk_count: 1,
      created_at: "2026-03-25T12:00:00Z",
      updated_at: "2026-03-25T12:00:00Z",
    });
    vi.mocked(adminApi.rollbackSnapshot).mockResolvedValue({
      rolled_back_from: {
        id: "active-1",
        name: "Active",
        status: "active",
        published_at: null,
        activated_at: null,
      },
      rolled_back_to: {
        id: "published-1",
        name: "Published",
        status: "published",
        published_at: null,
        activated_at: null,
      },
    });

    const { result } = renderHook(() => useSnapshots(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.publish("draft-1", false);
      await result.current.activate("published-1");
      await result.current.rollback("active-1");
    });

    expect(adminApi.publishSnapshot).toHaveBeenCalledWith("draft-1", false);
    expect(adminApi.activateSnapshot).toHaveBeenCalledWith("published-1");
    expect(adminApi.rollbackSnapshot).toHaveBeenCalledWith("active-1");
  });
});
