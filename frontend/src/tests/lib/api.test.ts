import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  type ApiError,
  buildApiUrl,
  createSession,
  getSession,
  getTwinAvatarUrl,
} from "@/lib/api";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

describe("api client", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("creates a session", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          id: "session-1",
          snapshot_id: "snapshot-1",
          status: "active",
          channel: "web",
          message_count: 0,
          created_at: "2026-03-25T12:00:00Z",
        },
        201,
      ),
    );

    const session = await createSession("access-token");

    expect(fetchMock).toHaveBeenCalledWith(buildApiUrl("/api/chat/sessions"), {
      method: "POST",
      headers: {
        Authorization: "Bearer access-token",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ channel: "web" }),
    });
    expect(session.id).toBe("session-1");
  });

  it("gets a session with history", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "session-1",
        snapshot_id: "snapshot-1",
        status: "active",
        channel: "web",
        message_count: 1,
        created_at: "2026-03-25T12:00:00Z",
        messages: [
          {
            id: "message-1",
            role: "user",
            content: "Hello",
            status: "received",
            citations: null,
            model_name: null,
            created_at: "2026-03-25T12:00:01Z",
          },
        ],
      }),
    );

    const session = await getSession("session-1", "access-token");

    expect(fetchMock).toHaveBeenCalledWith(
      buildApiUrl("/api/chat/sessions/session-1"),
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer access-token",
        },
      },
    );
    expect(session.messages).toHaveLength(1);
  });

  it("surfaces 404 errors with detail", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Session not found" }, 404),
    );

    await expect(getSession("missing", "access-token")).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: "ApiError",
        status: 404,
        message: "Session not found",
      }),
    );
  });

  it("returns a blob URL handle for the twin avatar and supports cleanup", async () => {
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:twin-avatar");
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});

    fetchMock.mockResolvedValueOnce(new Response(new Blob(["avatar-bytes"])));

    const avatar = await getTwinAvatarUrl("access-token");

    expect(fetchMock).toHaveBeenCalledWith(
      buildApiUrl("/api/chat/twin/avatar"),
      {
        method: "GET",
        headers: {
          Authorization: "Bearer access-token",
        },
      },
    );
    expect(avatar.url).toBe("blob:twin-avatar");
    avatar.revoke();
    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:twin-avatar");
  });
});
