import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { buildApiUrl } from "@/lib/api";
import { strings } from "@/lib/strings";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

function activeSessionResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: "session-1",
    snapshot_id: "snapshot-1",
    status: "active",
    channel: "web",
    message_count: 0,
    created_at: "2026-03-25T12:00:00Z",
    ...overrides,
  };
}

function authUserResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: "user-1",
    email: "user@example.com",
    status: "active",
    email_verified_at: "2026-03-25T11:59:00Z",
    created_at: "2026-03-25T11:58:00Z",
    profile: {
      display_name: "Test User",
      avatar_url: null,
    },
    ...overrides,
  };
}

function twinProfileResponse(overrides: Record<string, unknown> = {}) {
  return {
    name: "ProxyMind",
    has_avatar: false,
    ...overrides,
  };
}

function getRequestUrl(input: RequestInfo | URL) {
  if (typeof input === "string") {
    return input;
  }

  if (input instanceof URL) {
    return input.toString();
  }

  return input.url;
}

function stubLocalStorage() {
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
}

describe("Auth routes integration", () => {
  beforeEach(() => {
    stubLocalStorage();
    localStorage.clear();
    window.history.replaceState({}, "", "/");
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("redirects unauthenticated root visitors to sign-in", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === buildApiUrl("/api/auth/refresh") && init?.method === "POST") {
        return jsonResponse(
          { detail: "Invalid or expired refresh token" },
          401,
        );
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: strings.signInTitle }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/auth/sign-in");
    });
  });

  it("shows a loading state while silent refresh is pending", async () => {
    let resolveRefresh: (value: Response) => void = () => {
      throw new Error("Expected silent refresh resolver to be initialized");
    };
    const refreshResponse = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });

    fetchMock.mockImplementation((input, init) => {
      const url = getRequestUrl(input);

      if (url === buildApiUrl("/api/auth/refresh") && init?.method === "POST") {
        return refreshResponse;
      }

      if (url === buildApiUrl("/api/users/me") && init?.method === "GET") {
        return Promise.resolve(jsonResponse(authUserResponse()));
      }

      if (url === buildApiUrl("/api/chat/twin") && init?.method === "GET") {
        return Promise.resolve(jsonResponse(twinProfileResponse()));
      }

      if (
        url === buildApiUrl("/api/chat/sessions") &&
        init?.method === "POST"
      ) {
        return Promise.resolve(jsonResponse(activeSessionResponse(), 201));
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      screen.getByRole("heading", { name: strings.authLoading }),
    ).toBeInTheDocument();

    resolveRefresh(
      jsonResponse({
        access_token: "access-token",
        token_type: "bearer",
      }),
    );

    expect(
      await screen.findByLabelText(strings.inputPlaceholder),
    ).toBeInTheDocument();
  });

  it("renders chat for an authenticated user after silent refresh", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === buildApiUrl("/api/auth/refresh") && init?.method === "POST") {
        return jsonResponse({
          access_token: "access-token",
          token_type: "bearer",
        });
      }

      if (url === buildApiUrl("/api/users/me") && init?.method === "GET") {
        return jsonResponse(authUserResponse());
      }

      if (url === buildApiUrl("/api/chat/twin") && init?.method === "GET") {
        return jsonResponse(twinProfileResponse({ name: "Marcus Aurelius" }));
      }

      if (
        url === buildApiUrl("/api/chat/sessions") &&
        init?.method === "POST"
      ) {
        return jsonResponse(activeSessionResponse(), 201);
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      await screen.findByLabelText(strings.inputPlaceholder),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/");
    });
  });
});
