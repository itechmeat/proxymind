import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateSnapshot,
  createSnapshot,
  deleteSource,
  getSnapshots,
  getSources,
  publishSnapshot,
  rollbackSnapshot,
  testDraftSnapshot,
  uploadSource,
} from "@/lib/admin-api";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

describe("admin api client", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads sources", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: "source-1",
          title: "Doc",
          source_type: "pdf",
          status: "ready",
          description: null,
          public_url: null,
          file_size_bytes: 120,
          language: "en",
          created_at: "2026-03-25T12:00:00Z",
        },
      ]),
    );

    const response = await getSources();

    expect(fetchMock).toHaveBeenCalledWith("/api/admin/sources", {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    });
    expect(response[0]?.id).toBe("source-1");
  });

  it("uploads a source with multipart metadata", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          source_id: "source-1",
          task_id: "task-1",
          status: "pending",
          file_path: "/sources/source-1.pdf",
          message: "queued",
        },
        202,
      ),
    );

    await uploadSource(new File(["hello"], "hello.pdf"), { title: "hello" });

    const request = fetchMock.mock.calls[0];
    expect(request?.[0]).toBe("/api/admin/sources");
    expect(request?.[1]?.method).toBe("POST");
    expect(request?.[1]?.body).toBeInstanceOf(FormData);
  });

  it("sends snapshot lifecycle requests", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ id: "draft-1", status: "draft" }))
      .mockResolvedValueOnce(
        jsonResponse({ id: "snap-1", status: "published" }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: "snap-1", status: "active" }))
      .mockResolvedValueOnce(
        jsonResponse({
          rolled_back_from: {
            id: "active-1",
            name: "A",
            status: "active",
            published_at: null,
            activated_at: null,
          },
          rolled_back_to: {
            id: "published-1",
            name: "B",
            status: "published",
            published_at: null,
            activated_at: null,
          },
        }),
      );
    await getSnapshots();
    await getSnapshots(true);
    await createSnapshot();
    await publishSnapshot("snap-1", true);
    await activateSnapshot("snap-1");
    await rollbackSnapshot("snap-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/admin/snapshots",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/snapshots?include_archived=true",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/admin/snapshots",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/admin/snapshots/snap-1/publish?activate=true",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/admin/snapshots/snap-1/activate",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/admin/snapshots/snap-1/rollback",
      expect.any(Object),
    );
  });

  it("tests a draft snapshot", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        snapshot_id: "draft-1",
        snapshot_name: "Draft",
        query: "what changed",
        mode: "hybrid",
        total_chunks_in_draft: 2,
        results: [],
      }),
    );

    await testDraftSnapshot("draft-1", { query: "what changed" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/snapshots/draft-1/test",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
      }),
    );
  });

  it("deletes a source", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "source-1",
        title: "Doc",
        source_type: "pdf",
        status: "deleted",
        deleted_at: "2026-03-25T12:00:00Z",
        warnings: [],
      }),
    );

    await deleteSource("source-1");

    expect(fetchMock).toHaveBeenCalledWith("/api/admin/sources/source-1", {
      method: "DELETE",
      headers: {
        Accept: "application/json",
      },
    });
  });

  it("surfaces API error detail for admin requests", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Draft has no indexed chunks to search" }, 422),
    );

    await expect(
      testDraftSnapshot("draft-1", { query: "what changed" }),
    ).rejects.toMatchObject({
      message: "Draft has no indexed chunks to search",
      name: "ApiError",
      status: 422,
    });
  });
});
