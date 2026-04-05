export type UserStatus = "pending" | "active" | "blocked";

export interface AuthProfile {
  display_name: string | null;
  avatar_url: string | null;
}

export interface AuthUser {
  id: string;
  email: string;
  status: UserStatus;
  email_verified_at: string | null;
  created_at: string;
  profile: AuthProfile;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
}

export interface AuthMessageResponse {
  detail: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name?: string | null;
}

export interface SignInRequest {
  email: string;
  password: string;
}

export interface ResetPasswordRequest {
  new_password: string;
  token: string;
}

export interface UpdateMeRequest {
  avatar_url?: string | null;
  display_name?: string | null;
}
