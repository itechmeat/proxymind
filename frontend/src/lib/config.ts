import { strings } from "@/lib/strings";

const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");

export const appConfig = {
  apiUrl: trimTrailingSlash((import.meta.env.VITE_API_URL ?? "").trim()),
  adminMode: (import.meta.env.VITE_ADMIN_MODE ?? "").trim() === "true",
  language: (import.meta.env.VITE_DEFAULT_LANGUAGE ?? "en").trim() || "en",
  twinName:
    (import.meta.env.VITE_TWIN_NAME ?? strings.appTitle).trim() ||
    strings.appTitle,
  twinAvatarUrl: (import.meta.env.VITE_TWIN_AVATAR_URL ?? "").trim(),
} as const;
