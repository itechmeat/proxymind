import { HttpResponse, http } from "msw";

import type { AuthUser } from "@/types/auth";

const GENERIC_REGISTRATION_MESSAGE = "Check your email to verify your account.";
const GENERIC_FORGOT_PASSWORD_MESSAGE =
  "If the account exists, reset instructions have been sent.";

function buildMockUser(): AuthUser {
  return {
    id: "mock-user-00000000-0000-0000-0000-000000000001",
    email: "mock-user@example.com",
    status: "active",
    email_verified_at: "2026-04-05T09:00:00Z",
    created_at: "2026-04-05T08:00:00Z",
    profile: {
      display_name: "Mock User",
      avatar_url: null,
    },
  };
}

let currentUser = buildMockUser();
let currentPassword = "MockPass123!";
let isAuthenticated = true;
let accessTokenCounter = 0;

export function resetAuthMockState() {
  currentUser = buildMockUser();
  currentPassword = "MockPass123!";
  isAuthenticated = true;
  accessTokenCounter = 0;
}

function nextAccessToken() {
  accessTokenCounter += 1;
  return `mock-access-token-${accessTokenCounter}`;
}

function hasBearerHeader(request: Request) {
  const value = request.headers.get("Authorization");
  return typeof value === "string" && value.startsWith("Bearer ");
}

export const authHandlers = [
  http.get("*/api/admin/auth/me", ({ request }) => {
    const authorization = request.headers.get("Authorization");
    if (authorization !== "Bearer mock-admin-key") {
      return HttpResponse.json(
        { detail: "Invalid or missing API key" },
        { status: 401 },
      );
    }

    return HttpResponse.json({ ok: true });
  }),

  http.post("*/api/auth/register", async ({ request }) => {
    const body = (await request.json()) as {
      display_name?: string | null;
      email?: string;
      password?: string;
    };

    currentUser = {
      ...currentUser,
      email: body.email?.trim().toLowerCase() || currentUser.email,
      status: "pending",
      email_verified_at: null,
      profile: {
        ...currentUser.profile,
        display_name:
          body.display_name?.trim() || currentUser.profile.display_name,
      },
    };
    currentPassword = body.password || currentPassword;
    isAuthenticated = false;

    return HttpResponse.json({ detail: GENERIC_REGISTRATION_MESSAGE });
  }),

  http.post("*/api/auth/verify-email", () => {
    currentUser = {
      ...currentUser,
      status: "active",
      email_verified_at: new Date().toISOString(),
    };

    return HttpResponse.json({ detail: "Email verified successfully." });
  }),

  http.post("*/api/auth/sign-in", async ({ request }) => {
    const body = (await request.json()) as {
      email?: string;
      password?: string;
    };

    if (
      body.email?.trim().toLowerCase() !== currentUser.email ||
      body.password !== currentPassword
    ) {
      return HttpResponse.json(
        { detail: "Invalid email or password" },
        { status: 401 },
      );
    }

    if (currentUser.status === "pending") {
      return HttpResponse.json(
        { detail: "Email address is not verified" },
        { status: 403 },
      );
    }

    if (currentUser.status === "blocked") {
      return HttpResponse.json(
        { detail: "User account is blocked" },
        { status: 403 },
      );
    }

    isAuthenticated = true;
    return HttpResponse.json({
      access_token: nextAccessToken(),
      token_type: "bearer",
    });
  }),

  http.post("*/api/auth/refresh", () => {
    if (!isAuthenticated) {
      return HttpResponse.json(
        { detail: "Invalid or expired refresh token" },
        { status: 401 },
      );
    }

    return HttpResponse.json({
      access_token: nextAccessToken(),
      token_type: "bearer",
    });
  }),

  http.post("*/api/auth/sign-out", () => {
    isAuthenticated = false;
    return HttpResponse.json({ detail: "Signed out successfully." });
  }),

  http.post("*/api/auth/forgot-password", () => {
    return HttpResponse.json({ detail: GENERIC_FORGOT_PASSWORD_MESSAGE });
  }),

  http.post("*/api/auth/reset-password", async ({ request }) => {
    const body = (await request.json()) as { new_password?: string };
    currentPassword = body.new_password || currentPassword;
    isAuthenticated = false;
    return HttpResponse.json({ detail: "Password reset successfully." });
  }),

  http.get("*/api/users/me", ({ request }) => {
    if (!isAuthenticated || !hasBearerHeader(request)) {
      return HttpResponse.json(
        { detail: "Invalid or missing access token" },
        { status: 401 },
      );
    }

    return HttpResponse.json(currentUser);
  }),

  http.patch("*/api/profile", async ({ request }) => {
    if (!isAuthenticated || !hasBearerHeader(request)) {
      return HttpResponse.json(
        { detail: "Invalid or missing access token" },
        { status: 401 },
      );
    }

    const body = (await request.json()) as {
      display_name?: string | null;
      avatar_url?: string | null;
    };

    currentUser = {
      ...currentUser,
      profile: {
        display_name:
          body.display_name === undefined
            ? currentUser.profile.display_name
            : body.display_name,
        avatar_url:
          body.avatar_url === undefined
            ? currentUser.profile.avatar_url
            : body.avatar_url,
      },
    };

    return HttpResponse.json(currentUser);
  }),
];
