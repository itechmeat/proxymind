import { getAdminKey } from "@/hooks/useAuth";
import { appConfig } from "@/lib/config";
import { strings } from "@/lib/strings";
import type {
  AvatarUploadResponse,
  SessionResponse,
  SessionWithMessagesResponse,
  TwinProfile,
} from "@/types/chat";

export class ApiError extends Error {
  status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface BlobUrlHandle {
  revoke: () => void;
  url: string;
}

export function buildApiUrl(pathname: string) {
  if (!appConfig.apiUrl) {
    return pathname;
  }

  return `${appConfig.apiUrl}${pathname}`;
}

export async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  let detail = strings.requestFailed(response.status);

  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim()) {
      detail = body.detail;
    } else if (Array.isArray(body.detail) && body.detail.length > 0) {
      detail = JSON.stringify(body.detail[0]);
    }
  } catch {
    // Ignore non-JSON errors and surface the status-based fallback message.
  }

  throw new ApiError(response.status, detail);
}

function endUserAuthHeaders(accessToken?: string): Record<string, string> {
  if (!accessToken) {
    return {};
  }

  return {
    Authorization: `Bearer ${accessToken}`,
  };
}

export async function createSession(
  accessToken: string,
): Promise<SessionResponse> {
  const response = await fetch(buildApiUrl("/api/chat/sessions"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...endUserAuthHeaders(accessToken),
    },
    body: JSON.stringify({ channel: "web" }),
  });

  return parseJsonResponse<SessionResponse>(response);
}

export async function getSession(
  sessionId: string,
  accessToken: string,
): Promise<SessionWithMessagesResponse> {
  const response = await fetch(
    buildApiUrl(`/api/chat/sessions/${encodeURIComponent(sessionId)}`),
    {
      method: "GET",
      headers: {
        Accept: "application/json",
        ...endUserAuthHeaders(accessToken),
      },
    },
  );

  return parseJsonResponse<SessionWithMessagesResponse>(response);
}

export async function getTwinProfile(
  accessToken?: string,
): Promise<TwinProfile> {
  const response = await fetch(buildApiUrl("/api/chat/twin"), {
    method: "GET",
    headers: {
      Accept: "application/json",
      ...endUserAuthHeaders(accessToken),
    },
  });

  return parseJsonResponse<TwinProfile>(response);
}

export async function getTwinAvatarUrl(
  accessToken: string,
): Promise<BlobUrlHandle> {
  const response = await fetch(buildApiUrl("/api/chat/twin/avatar"), {
    method: "GET",
    headers: {
      ...endUserAuthHeaders(accessToken),
    },
  });

  if (!response.ok) {
    await parseJsonResponse<never>(response);
  }

  const avatarBlob = await response.blob();
  const url = URL.createObjectURL(avatarBlob);
  return {
    url,
    revoke: () => {
      URL.revokeObjectURL(url);
    },
  };
}

function adminAuthHeaders(): Record<string, string> {
  const key = getAdminKey();
  if (!key) {
    return {};
  }
  return { Authorization: `Bearer ${key}` };
}

export async function updateTwinProfile(name: string): Promise<TwinProfile> {
  const response = await fetch(buildApiUrl("/api/admin/agent/profile"), {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      ...adminAuthHeaders(),
    },
    body: JSON.stringify({ name }),
  });

  return parseJsonResponse<TwinProfile>(response);
}

export async function uploadTwinAvatar(
  file: File,
): Promise<AvatarUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(buildApiUrl("/api/admin/agent/avatar"), {
    method: "POST",
    headers: adminAuthHeaders(),
    body: formData,
  });

  return parseJsonResponse<AvatarUploadResponse>(response);
}

export async function deleteTwinAvatar(): Promise<AvatarUploadResponse> {
  const response = await fetch(buildApiUrl("/api/admin/agent/avatar"), {
    method: "DELETE",
    headers: {
      Accept: "application/json",
      ...adminAuthHeaders(),
    },
  });

  return parseJsonResponse<AvatarUploadResponse>(response);
}
