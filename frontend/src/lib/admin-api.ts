import { buildApiUrl, parseJsonResponse } from "@/lib/api";
import type {
  DraftTestResponse,
  RetrievalMode,
  RollbackResponse,
  SnapshotResponse,
  SourceDeleteResponse,
  SourceListItem,
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
