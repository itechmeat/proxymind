import { buildApiUrl, parseJsonResponse } from "@/lib/api";
import type {
  CatalogItem,
  CatalogItemCreate,
  CatalogItemDetail,
  CatalogItemListResponse,
  CatalogItemType,
  CatalogItemUpdate,
  DraftTestResponse,
  RetrievalMode,
  RollbackResponse,
  SnapshotResponse,
  SourceDeleteResponse,
  SourceListItem,
  SourceUpdateRequest,
  SourceUploadMetadata,
  SourceUploadResponse,
} from "@/types/admin";

export async function getSources(): Promise<SourceListItem[]> {
  const response = await fetch(buildApiUrl("/api/admin/sources"), {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
  });

  return parseJsonResponse<SourceListItem[]>(response);
}

export async function uploadSource(
  file: File,
  metadata: SourceUploadMetadata,
): Promise<SourceUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("metadata", JSON.stringify(metadata));

  const response = await fetch(buildApiUrl("/api/admin/sources"), {
    method: "POST",
    body: formData,
  });

  return parseJsonResponse<SourceUploadResponse>(response);
}

export async function deleteSource(
  sourceId: string,
): Promise<SourceDeleteResponse> {
  const response = await fetch(
    buildApiUrl(`/api/admin/sources/${encodeURIComponent(sourceId)}`),
    {
      method: "DELETE",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return parseJsonResponse<SourceDeleteResponse>(response);
}

export async function getSnapshots(
  includeArchived = false,
): Promise<SnapshotResponse[]> {
  const query = includeArchived ? "?include_archived=true" : "";
  const response = await fetch(buildApiUrl(`/api/admin/snapshots${query}`), {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
  });

  return parseJsonResponse<SnapshotResponse[]>(response);
}

export async function createSnapshot(): Promise<SnapshotResponse> {
  const response = await fetch(buildApiUrl("/api/admin/snapshots"), {
    method: "POST",
    headers: {
      Accept: "application/json",
    },
  });

  return parseJsonResponse<SnapshotResponse>(response);
}

export async function publishSnapshot(
  snapshotId: string,
  activate = false,
): Promise<SnapshotResponse> {
  const query = activate ? "?activate=true" : "";
  const response = await fetch(
    buildApiUrl(
      `/api/admin/snapshots/${encodeURIComponent(snapshotId)}/publish${query}`,
    ),
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return parseJsonResponse<SnapshotResponse>(response);
}

export async function activateSnapshot(
  snapshotId: string,
): Promise<SnapshotResponse> {
  const response = await fetch(
    buildApiUrl(
      `/api/admin/snapshots/${encodeURIComponent(snapshotId)}/activate`,
    ),
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return parseJsonResponse<SnapshotResponse>(response);
}

export async function rollbackSnapshot(
  snapshotId: string,
): Promise<RollbackResponse> {
  const response = await fetch(
    buildApiUrl(
      `/api/admin/snapshots/${encodeURIComponent(snapshotId)}/rollback`,
    ),
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return parseJsonResponse<RollbackResponse>(response);
}

export async function testDraftSnapshot(
  snapshotId: string,
  payload: {
    query: string;
    top_n?: number;
    mode?: RetrievalMode;
  },
): Promise<DraftTestResponse> {
  const response = await fetch(
    buildApiUrl(`/api/admin/snapshots/${encodeURIComponent(snapshotId)}/test`),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        top_n: payload.top_n ?? 5,
        mode: payload.mode ?? "hybrid",
        query: payload.query,
      }),
    },
  );

  return parseJsonResponse<DraftTestResponse>(response);
}

export async function getCatalogItems(
  itemType?: CatalogItemType,
): Promise<CatalogItemListResponse> {
  const params = new URLSearchParams();
  if (itemType) {
    params.set("item_type", itemType);
  }
  params.set("limit", "100");

  const query = params.toString();
  const response = await fetch(buildApiUrl(`/api/admin/catalog?${query}`), {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
  });

  return parseJsonResponse<CatalogItemListResponse>(response);
}

export async function getCatalogItem(
  catalogItemId: string,
): Promise<CatalogItemDetail> {
  const response = await fetch(
    buildApiUrl(`/api/admin/catalog/${encodeURIComponent(catalogItemId)}`),
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return parseJsonResponse<CatalogItemDetail>(response);
}

export async function createCatalogItem(
  data: CatalogItemCreate,
): Promise<CatalogItem> {
  const response = await fetch(buildApiUrl("/api/admin/catalog"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(data),
  });

  return parseJsonResponse<CatalogItem>(response);
}

export async function updateCatalogItem(
  catalogItemId: string,
  data: CatalogItemUpdate,
): Promise<CatalogItem> {
  const response = await fetch(
    buildApiUrl(`/api/admin/catalog/${encodeURIComponent(catalogItemId)}`),
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(data),
    },
  );

  return parseJsonResponse<CatalogItem>(response);
}

export async function deleteCatalogItem(
  catalogItemId: string,
): Promise<CatalogItem> {
  const response = await fetch(
    buildApiUrl(`/api/admin/catalog/${encodeURIComponent(catalogItemId)}`),
    {
      method: "DELETE",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return parseJsonResponse<CatalogItem>(response);
}

export async function updateSource(
  sourceId: string,
  data: SourceUpdateRequest,
): Promise<SourceListItem> {
  const response = await fetch(
    buildApiUrl(`/api/admin/sources/${encodeURIComponent(sourceId)}`),
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(data),
    },
  );

  return parseJsonResponse<SourceListItem>(response);
}
