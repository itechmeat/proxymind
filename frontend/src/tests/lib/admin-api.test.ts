import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateSnapshot,
  createCatalogItem,
  createSnapshot,
  deleteCatalogItem,
  deleteSource,
  getCatalogItem,
  getCatalogItems,
  getSnapshots,
  getSources,
  publishSnapshot,
  rollbackSnapshot,
  testDraftSnapshot,
  updateCatalogItem,
  updateSource,
  uploadSource,
} from "@/lib/admin-api";
import { buildApiUrl } from "@/lib/api";

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
          catalog_item_id: null,
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

    expect(fetchMock).toHaveBeenCalledWith(buildApiUrl("/api/admin/sources"), {
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
    expect(request?.[0]).toBe(buildApiUrl("/api/admin/sources"));
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
      buildApiUrl("/api/admin/snapshots"),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      buildApiUrl("/api/admin/snapshots?include_archived=true"),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      buildApiUrl("/api/admin/snapshots"),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      buildApiUrl("/api/admin/snapshots/snap-1/publish?activate=true"),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      buildApiUrl("/api/admin/snapshots/snap-1/activate"),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      buildApiUrl("/api/admin/snapshots/snap-1/rollback"),
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
      buildApiUrl("/api/admin/snapshots/draft-1/test"),
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

    expect(fetchMock).toHaveBeenCalledWith(
      buildApiUrl("/api/admin/sources/source-1"),
      {
        method: "DELETE",
        headers: {
          Accept: "application/json",
        },
      },
    );
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

  it("performs catalog CRUD requests", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
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
              linked_sources_count: 1,
            },
          ],
          total: 1,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
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
          linked_sources_count: 1,
          linked_sources: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
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
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "catalog-1",
          sku: "BOOK-001",
          name: "AI in Practice 2nd Ed",
          description: null,
          item_type: "book",
          url: null,
          image_url: null,
          is_active: true,
          valid_from: null,
          valid_until: null,
          created_at: "2026-03-25T12:00:00Z",
          updated_at: "2026-03-25T12:05:00Z",
          linked_sources_count: 0,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "catalog-1",
          sku: "BOOK-001",
          name: "AI in Practice 2nd Ed",
          description: null,
          item_type: "book",
          url: null,
          image_url: null,
          is_active: false,
          valid_from: null,
          valid_until: null,
          created_at: "2026-03-25T12:00:00Z",
          updated_at: "2026-03-25T12:10:00Z",
          linked_sources_count: 0,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "source-1",
          catalog_item_id: "catalog-1",
          title: "Doc",
          source_type: "pdf",
          status: "ready",
          description: null,
          public_url: null,
          file_size_bytes: 120,
          language: "en",
          created_at: "2026-03-25T12:00:00Z",
        }),
      );

    await getCatalogItems();
    await getCatalogItem("catalog-1");
    await createCatalogItem({
      sku: "BOOK-001",
      name: "AI in Practice",
      item_type: "book",
    });
    await updateCatalogItem("catalog-1", { name: "AI in Practice 2nd Ed" });
    await deleteCatalogItem("catalog-1");
    await updateSource("source-1", { catalog_item_id: "catalog-1" });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      buildApiUrl("/api/admin/catalog?limit=100"),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      buildApiUrl("/api/admin/catalog/catalog-1"),
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      buildApiUrl("/api/admin/catalog"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      buildApiUrl("/api/admin/catalog/catalog-1"),
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      buildApiUrl("/api/admin/catalog/catalog-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      buildApiUrl("/api/admin/sources/source-1"),
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("includes item type filter when loading catalog items", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [],
        total: 0,
      }),
    );

    await getCatalogItems("book");

    expect(fetchMock).toHaveBeenCalledWith(
      buildApiUrl("/api/admin/catalog?item_type=book&limit=100"),
      expect.objectContaining({ method: "GET" }),
    );
  });
});
