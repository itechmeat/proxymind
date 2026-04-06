import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AuthProvider, useUserAuth } from "@/hooks/useUserAuth";

const {
  forgotPasswordMock,
  getMeMock,
  refreshUserTokenMock,
  registerUserMock,
  resetPasswordMock,
  signInUserMock,
  signOutUserMock,
  verifyEmailMock,
} = vi.hoisted(() => ({
  forgotPasswordMock: vi.fn(),
  getMeMock: vi.fn(),
  refreshUserTokenMock: vi.fn(),
  registerUserMock: vi.fn(),
  resetPasswordMock: vi.fn(),
  signInUserMock: vi.fn(),
  signOutUserMock: vi.fn(),
  verifyEmailMock: vi.fn(),
}));

vi.mock("@/lib/auth-api", () => ({
  forgotPassword: forgotPasswordMock,
  getMe: getMeMock,
  refreshUserToken: refreshUserTokenMock,
  registerUser: registerUserMock,
  resetPassword: resetPasswordMock,
  signInUser: signInUserMock,
  signOutUser: signOutUserMock,
  verifyEmail: verifyEmailMock,
}));

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("useUserAuth", () => {
  it("ignores a stale bootstrap refresh result after sign-out", async () => {
    let resolveRefresh:
      | ((value: { access_token: string; token_type: string }) => void)
      | null = null;

    refreshUserTokenMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }),
    );
    signOutUserMock.mockResolvedValueOnce({
      detail: "Signed out successfully.",
    });
    getMeMock.mockResolvedValue({
      id: "user-1",
      email: "user@example.com",
      status: "active",
      email_verified_at: "2026-04-05T09:00:00Z",
      created_at: "2026-04-05T08:00:00Z",
      profile: {
        display_name: "Test User",
        avatar_url: null,
      },
    });

    const { result } = renderHook(() => useUserAuth(), { wrapper });

    await act(async () => {
      await result.current.signOut();
    });

    expect(result.current.isAuthenticated).toBe(false);

    await act(async () => {
      resolveRefresh?.({
        access_token: "late-access-token",
        token_type: "bearer",
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });
});
