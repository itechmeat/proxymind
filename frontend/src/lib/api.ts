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

export function buildApiUrl(pathname: string) {
  if (!appConfig.apiUrl) {
    return pathname;
  }

  return `${appConfig.apiUrl}${pathname}`;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  let detail = strings.requestFailed(response.status);

  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) {
      detail = body.detail;
    }
  } catch {
    // Ignore non-JSON errors and surface the status-based fallback message.
  }

  throw new ApiError(response.status, detail);
}

export async function createSession(): Promise<SessionResponse> {
  const response = await fetch(buildApiUrl("/api/chat/sessions"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ channel: "web" }),
  });

  return parseJsonResponse<SessionResponse>(response);
}

export async function getSession(
  sessionId: string,
): Promise<SessionWithMessagesResponse> {
  const response = await fetch(
    buildApiUrl(`/api/chat/sessions/${encodeURIComponent(sessionId)}`),
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return parseJsonResponse<SessionWithMessagesResponse>(response);
}

export async function getTwinProfile(): Promise<TwinProfile> {
  const response = await fetch(buildApiUrl("/api/chat/twin"), {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
  });

  return parseJsonResponse<TwinProfile>(response);
}

export async function updateTwinProfile(name: string): Promise<TwinProfile> {
  const response = await fetch(buildApiUrl("/api/admin/agent/profile"), {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
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
    body: formData,
  });

  return parseJsonResponse<AvatarUploadResponse>(response);
}

export async function deleteTwinAvatar(): Promise<AvatarUploadResponse> {
  const response = await fetch(buildApiUrl("/api/admin/agent/avatar"), {
    method: "DELETE",
    headers: {
      Accept: "application/json",
    },
  });

  return parseJsonResponse<AvatarUploadResponse>(response);
}
