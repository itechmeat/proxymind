import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
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

describe("Admin routes integration", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("redirects /admin to /admin/sources in admin mode", async () => {
    appConfig.adminMode = true;
    window.history.replaceState({}, "", "/admin");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse({ name: "ProxyMind", has_avatar: false });
      }

      if (url === "/api/admin/sources" && init?.method === "GET") {
        return jsonResponse([]);
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
    window.history.replaceState({}, "", "/admin/sources");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse({ name: "ProxyMind", has_avatar: false });
      }

      if (url === "/api/admin/sources" && init?.method === "GET") {
        return jsonResponse([]);
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
  });

  it("redirects admin routes to chat when admin mode is disabled", async () => {
    appConfig.adminMode = false;
    window.history.replaceState({}, "", "/admin/sources");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse({ name: "ProxyMind", has_avatar: false });
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
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
      await screen.findByRole("heading", { name: "ProxyMind" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/");
    });
  });
});
