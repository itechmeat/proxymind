import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { strings } from "@/lib/strings";
import {
  ForgotPasswordPage,
  RegisterPage,
  ResetPasswordPage,
  VerifyEmailPage,
} from "@/pages/AuthPage";

const {
  forgotPasswordMock,
  registerMock,
  resetPasswordMock,
  signInMock,
  signOutMock,
  verifyEmailMock,
} = vi.hoisted(() => ({
  forgotPasswordMock: vi.fn(),
  registerMock: vi.fn(),
  resetPasswordMock: vi.fn(),
  signInMock: vi.fn(),
  signOutMock: vi.fn(),
  verifyEmailMock: vi.fn(),
}));

vi.mock("@/hooks/useUserAuth", () => ({
  useUserAuth: () => ({
    accessToken: null,
    forgotPassword: forgotPasswordMock,
    getAccessToken: vi.fn().mockResolvedValue(null),
    isAuthenticated: false,
    isLoading: false,
    register: registerMock,
    resetPassword: resetPasswordMock,
    signIn: signInMock,
    signOut: signOutMock,
    user: null,
    verifyEmail: verifyEmailMock,
  }),
}));

function renderWithRouter(pathname: string, element: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Routes>
        <Route element={element} path="*" />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Auth pages", () => {
  beforeEach(() => {
    forgotPasswordMock.mockReset();
    registerMock.mockReset();
    resetPasswordMock.mockReset();
    signInMock.mockReset();
    signOutMock.mockReset();
    verifyEmailMock.mockReset();
  });

  it("blocks registration when password confirmation does not match", async () => {
    const user = userEvent.setup();
    renderWithRouter("/auth/register", <RegisterPage />);

    await user.type(
      screen.getByLabelText(strings.displayNameLabel),
      "Test User",
    );
    await user.type(
      screen.getByLabelText(strings.emailLabel),
      "user@example.com",
    );
    await user.type(screen.getByLabelText(strings.passwordLabel), "Start123!");
    await user.type(
      screen.getByLabelText(strings.confirmPasswordLabel),
      "Mismatch123!",
    );
    await user.click(
      screen.getByRole("button", { name: strings.registerAction }),
    );

    expect(
      await screen.findByText(strings.passwordConfirmationMismatch),
    ).toBeInTheDocument();
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("blocks password reset when confirmation does not match", async () => {
    const user = userEvent.setup();
    renderWithRouter(
      "/auth/reset-password?token=test-token",
      <ResetPasswordPage />,
    );

    await user.clear(screen.getByLabelText(strings.resetTokenLabel));
    await user.type(
      screen.getByLabelText(strings.resetTokenLabel),
      "test-token",
    );
    await user.type(
      screen.getByLabelText(strings.newPasswordLabel),
      "Updated123!",
    );
    await user.type(
      screen.getByLabelText(strings.confirmPasswordLabel),
      "Mismatch123!",
    );
    await user.click(
      screen.getByRole("button", { name: strings.resetPasswordAction }),
    );

    expect(
      await screen.findByText(strings.passwordConfirmationMismatch),
    ).toBeInTheDocument();
    expect(resetPasswordMock).not.toHaveBeenCalled();
  });

  it("verifies the token only once in StrictMode", async () => {
    verifyEmailMock.mockResolvedValueOnce("Email verified successfully.");

    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/auth/verify-email?token=test-token"]}>
          <Routes>
            <Route element={<VerifyEmailPage />} path="*" />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );

    await waitFor(() => {
      expect(verifyEmailMock).toHaveBeenCalledTimes(1);
    });
    expect(verifyEmailMock).toHaveBeenCalledWith("test-token");
  });

  it("disables registration after a successful submit", async () => {
    const user = userEvent.setup();
    registerMock.mockResolvedValueOnce(
      "Check your email to verify your account.",
    );

    renderWithRouter("/auth/register", <RegisterPage />);

    await user.type(
      screen.getByLabelText(strings.displayNameLabel),
      "Test User",
    );
    await user.type(
      screen.getByLabelText(strings.emailLabel),
      "user@example.com",
    );
    await user.type(screen.getByLabelText(strings.passwordLabel), "Start123!");
    await user.type(
      screen.getByLabelText(strings.confirmPasswordLabel),
      "Start123!",
    );
    await user.click(
      screen.getByRole("button", { name: strings.registerAction }),
    );

    const submitButton = await screen.findByRole("button", {
      name: strings.registerAction,
    });
    expect(submitButton).toBeDisabled();

    await user.click(submitButton);
    expect(registerMock).toHaveBeenCalledTimes(1);
  });

  it("disables forgot-password resubmission after success", async () => {
    const user = userEvent.setup();
    forgotPasswordMock.mockResolvedValueOnce("Reset link sent.");

    renderWithRouter("/auth/forgot-password", <ForgotPasswordPage />);

    await user.type(
      screen.getByLabelText(strings.emailLabel),
      "user@example.com",
    );
    await user.click(
      screen.getByRole("button", { name: strings.sendResetLink }),
    );

    const submitButton = await screen.findByRole("button", {
      name: strings.sendResetLink,
    });
    expect(submitButton).toBeDisabled();

    await user.click(submitButton);
    expect(forgotPasswordMock).toHaveBeenCalledTimes(1);
  });

  it("disables password reset resubmission after success", async () => {
    const user = userEvent.setup();
    resetPasswordMock.mockResolvedValueOnce("Password reset complete.");

    renderWithRouter(
      "/auth/reset-password?token=test-token",
      <ResetPasswordPage />,
    );

    await user.clear(screen.getByLabelText(strings.resetTokenLabel));
    await user.type(
      screen.getByLabelText(strings.resetTokenLabel),
      "test-token",
    );
    await user.type(
      screen.getByLabelText(strings.newPasswordLabel),
      "Updated123!",
    );
    await user.type(
      screen.getByLabelText(strings.confirmPasswordLabel),
      "Updated123!",
    );
    await user.click(
      screen.getByRole("button", { name: strings.resetPasswordAction }),
    );

    const submitButton = await screen.findByRole("button", {
      name: strings.resetPasswordAction,
    });
    expect(submitButton).toBeDisabled();

    await user.click(submitButton);
    expect(resetPasswordMock).toHaveBeenCalledTimes(1);
  });
});
