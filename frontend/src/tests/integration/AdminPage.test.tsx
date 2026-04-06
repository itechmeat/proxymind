import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { buildApiUrl } from "@/lib/api";
import { appConfig } from "@/lib/config";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
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

function authUserResponse() {
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
  };
}

describe("Admin routes integration", () => {
  let originalAdminMode: boolean;

  beforeEach(() => {
    originalAdminMode = appConfig.adminMode;
    stubLocalStorage();
    localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    appConfig.adminMode = originalAdminMode;
    vi.unstubAllGlobals();
  });

  it("keeps the user on admin sign-in when the API key is invalid", async () => {
    const user = userEvent.setup();
    appConfig.adminMode = true;
    window.history.replaceState({}, "", "/admin/sign-in");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === buildApiUrl("/api/admin/auth/me") && init?.method === "GET") {
        return jsonResponse({ detail: "Invalid or missing API key" }, 401);
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    await user.type(
      await screen.findByLabelText(/admin api key/i),
      "not-a-real-admin-key",
    );
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(
      await screen.findByText(/invalid or missing api key/i),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/admin/sign-in");
    });
  });

  it("validates the admin key before entering the control surface", async () => {
    const user = userEvent.setup();
    appConfig.adminMode = true;
    window.history.replaceState({}, "", "/admin/sign-in");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === buildApiUrl("/api/admin/auth/me") && init?.method === "GET") {
        return jsonResponse({ ok: true });
      }

      if (url === buildApiUrl("/api/chat/twin") && init?.method === "GET") {
        return jsonResponse({ name: "ProxyMind", has_avatar: false });
      }

      if (url === buildApiUrl("/api/admin/sources") && init?.method === "GET") {
        return jsonResponse([]);
      }

      if (
        url === buildApiUrl("/api/admin/catalog?limit=100") &&
        init?.method === "GET"
      ) {
        return jsonResponse({ items: [], total: 0 });
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    await user.type(
      await screen.findByLabelText(/admin api key/i),
      "admin-key",
    );
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(
      await screen.findByText(/drop files to add new sources/i),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/admin/sources");
    });
  });

  it("redirects /admin to /admin/sources in admin mode", async () => {
    appConfig.adminMode = true;
    localStorage.setItem("proxymind_admin_key", "admin-key");
    window.history.replaceState({}, "", "/admin");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse({ name: "ProxyMind", has_avatar: false });
      }

      if (url === "/api/admin/sources" && init?.method === "GET") {
        return jsonResponse([]);
      }

      if (url === "/api/admin/catalog?limit=100" && init?.method === "GET") {
        return jsonResponse({ items: [], total: 0 });
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      await screen.findByText(/drop files to add new sources/i),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/admin/sources");
    });
  });

  it("renders the snapshots tab and switches via top navigation", async () => {
    const user = userEvent.setup();
    appConfig.adminMode = true;
    localStorage.setItem("proxymind_admin_key", "admin-key");
    window.history.replaceState({}, "", "/admin/sources");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse({ name: "ProxyMind", has_avatar: false });
      }

      if (url === "/api/admin/sources" && init?.method === "GET") {
        return jsonResponse([]);
      }

      if (url === "/api/admin/catalog?limit=100" && init?.method === "GET") {
        return jsonResponse({ items: [], total: 0 });
      }

      if (url === "/api/admin/snapshots" && init?.method === "GET") {
        return jsonResponse([]);
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    await user.click(await screen.findByRole("link", { name: "Snapshots" }));

    expect(
      await screen.findByText(
        /manage drafts, publications, activation and rollback/i,
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Catalog" }));

    expect(
      await screen.findByRole("button", { name: /add product/i }),
    ).toBeInTheDocument();
  });

  it("redirects admin routes to chat when admin mode is disabled", async () => {
    appConfig.adminMode = false;
    window.history.replaceState({}, "", "/admin/sources");

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
        return jsonResponse({ name: "ProxyMind", has_avatar: false });
      }

      if (
        url === buildApiUrl("/api/chat/sessions") &&
        init?.method === "POST"
      ) {
        return jsonResponse(
          {
            id: "session-1",
            snapshot_id: "snapshot-1",
            status: "active",
            channel: "web",
            message_count: 0,
            created_at: "2026-03-25T12:00:00Z",
          },
          201,
        );
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      await screen.findByLabelText(/ask proxymind something/i),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/");
    });
  });
});
