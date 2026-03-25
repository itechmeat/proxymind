import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SESSION_STORAGE_KEY, useSession } from "@/hooks/useSession";
import { ApiError } from "@/lib/api";

const { createSessionMock, getSessionMock } = vi.hoisted(() => ({
  createSessionMock: vi.fn(),
  getSessionMock: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");

  return {
    ...actual,
    createSession: createSessionMock,
    getSession: getSessionMock,
  };
});

describe("useSession", () => {
  beforeEach(() => {
    const storage = new Map<string, string>();

    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
      clear: () => {
        storage.clear();
      },
    });

    createSessionMock.mockReset();
    getSessionMock.mockReset();
    localStorage.clear();
  });

  it("creates a new session on first visit", async () => {
    createSessionMock.mockResolvedValueOnce({
      id: "session-new",
      snapshot_id: "snapshot-1",
      status: "active",
      channel: "web",
      message_count: 0,
      created_at: "2026-03-25T12:00:00Z",
    });

    const { result } = renderHook(() => useSession());

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(createSessionMock).toHaveBeenCalledTimes(1);
    expect(result.current.sessionId).toBe("session-new");
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBe("session-new");
  });

  it("restores a stored session from localStorage", async () => {
    localStorage.setItem(SESSION_STORAGE_KEY, "session-existing");
    getSessionMock.mockResolvedValueOnce({
      id: "session-existing",
      snapshot_id: "snapshot-1",
      status: "active",
      channel: "web",
      message_count: 1,
      created_at: "2026-03-25T12:00:00Z",
      messages: [
        {
          id: "message-1",
          role: "assistant",
          content: "Restored",
          status: "complete",
          citations: null,
          model_name: null,
          created_at: "2026-03-25T12:00:01Z",
        },
      ],
    });

    const { result } = renderHook(() => useSession());

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(getSessionMock).toHaveBeenCalledWith("session-existing");
    expect(result.current.initialMessages).toHaveLength(1);
    expect(result.current.initialMessages[0].parts[0]).toMatchObject({
      type: "text",
      text: "Restored",
    });
  });

  it("creates a new session when restore returns 404", async () => {
    localStorage.setItem(SESSION_STORAGE_KEY, "session-missing");
    getSessionMock.mockRejectedValueOnce(
      new ApiError(404, "Session not found"),
    );
    createSessionMock.mockResolvedValueOnce({
      id: "session-recreated",
      snapshot_id: null,
      status: "active",
      channel: "web",
      message_count: 0,
      created_at: "2026-03-25T12:00:00Z",
    });

    const { result } = renderHook(() => useSession());

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(getSessionMock).toHaveBeenCalledWith("session-missing");
    expect(createSessionMock).toHaveBeenCalledTimes(1);
    expect(result.current.sessionId).toBe("session-recreated");
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBe("session-recreated");
  });

  it("createNewSession replaces the current session", async () => {
    createSessionMock
      .mockResolvedValueOnce({
        id: "session-initial",
        snapshot_id: null,
        status: "active",
        channel: "web",
        message_count: 0,
        created_at: "2026-03-25T12:00:00Z",
      })
      .mockResolvedValueOnce({
        id: "session-replaced",
        snapshot_id: null,
        status: "active",
        channel: "web",
        message_count: 0,
        created_at: "2026-03-25T12:00:10Z",
      });

    const { result } = renderHook(() => useSession());

    await waitFor(() =>
      expect(result.current.sessionId).toBe("session-initial"),
    );

    await act(async () => {
      await result.current.createNewSession();
    });

    expect(result.current.sessionId).toBe("session-replaced");
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBe("session-replaced");
    expect(result.current.initialMessages).toEqual([]);
  });

  it("surfaces restore errors instead of leaving the hook unresolved", async () => {
    localStorage.setItem(SESSION_STORAGE_KEY, "session-broken");
    getSessionMock.mockRejectedValueOnce(
      new ApiError(503, "Backend unavailable"),
    );

    const { result } = renderHook(() => useSession());

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).toBe("Backend unavailable");
    expect(result.current.sessionId).toBeNull();
    expect(result.current.initialMessages).toEqual([]);
  });

  it("creates a session when localStorage access throws", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("Storage blocked");
      },
      setItem: () => {
        throw new Error("Storage blocked");
      },
      removeItem: () => {},
      clear: () => {},
    });

    createSessionMock.mockResolvedValueOnce({
      id: "session-storage-fallback",
      snapshot_id: null,
      status: "active",
      channel: "web",
      message_count: 0,
      created_at: "2026-03-25T12:00:00Z",
    });

    const { result } = renderHook(() => useSession());

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(createSessionMock).toHaveBeenCalledTimes(1);
    expect(result.current.sessionId).toBe("session-storage-fallback");
    expect(result.current.error).toBeNull();
  });
});
