import { buildApiUrl, parseJsonResponse } from "@/lib/api";
import type {
  AuthMessageResponse,
  AuthTokenResponse,
  AuthUser,
  RegisterRequest,
  ResetPasswordRequest,
  SignInRequest,
  UpdateMeRequest,
} from "@/types/auth";

function jsonHeaders(accessToken?: string) {
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(accessToken
      ? {
          Authorization: `Bearer ${accessToken}`,
        }
      : {}),
  };
}

export async function registerUser(
  payload: RegisterRequest,
): Promise<AuthMessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/register"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<AuthMessageResponse>(response);
}

export async function signInUser(
  payload: SignInRequest,
): Promise<AuthTokenResponse> {
  const response = await fetch(buildApiUrl("/api/auth/sign-in"), {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<AuthTokenResponse>(response);
}

export async function refreshUserToken(
  refreshToken?: string,
): Promise<AuthTokenResponse> {
  const response = await fetch(buildApiUrl("/api/auth/refresh"), {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "include",
    ...(refreshToken
      ? {
          body: JSON.stringify({
            refresh_token: refreshToken,
          }),
        }
      : {}),
  });

  return parseJsonResponse<AuthTokenResponse>(response);
}

export async function signOutUser(
  refreshToken?: string,
): Promise<AuthMessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/sign-out"), {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "include",
    ...(refreshToken
      ? {
          body: JSON.stringify({
            refresh_token: refreshToken,
          }),
        }
      : {}),
  });

  return parseJsonResponse<AuthMessageResponse>(response);
}

export async function forgotPassword(
  email: string,
): Promise<AuthMessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/forgot-password"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ email }),
  });

  return parseJsonResponse<AuthMessageResponse>(response);
}

export async function resetPassword(
  payload: ResetPasswordRequest,
): Promise<AuthMessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/reset-password"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<AuthMessageResponse>(response);
}

export async function verifyEmail(token: string): Promise<AuthMessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/verify-email"), {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ token }),
  });

  return parseJsonResponse<AuthMessageResponse>(response);
}

export async function getMe(accessToken: string): Promise<AuthUser> {
  const response = await fetch(buildApiUrl("/api/users/me"), {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });

  return parseJsonResponse<AuthUser>(response);
}

export async function updateMe(
  accessToken: string,
  payload: UpdateMeRequest,
): Promise<AuthUser> {
  const response = await fetch(buildApiUrl("/api/profile"), {
    method: "PATCH",
    headers: jsonHeaders(accessToken),
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<AuthUser>(response);
}
