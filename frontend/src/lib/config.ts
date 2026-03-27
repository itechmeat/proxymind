import { strings } from "@/lib/strings";

const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");

function resolveConfiguredLanguage(value: string | undefined) {
  return (value ?? "en").trim() || "en";
}

export function getPrimaryLanguageTag(language: string) {
  return language.trim().toLowerCase().split(/[-_]/)[0] || "en";
}

const configuredLanguage = resolveConfiguredLanguage(
  import.meta.env.VITE_DEFAULT_LANGUAGE,
);

type AppConfig = {
  apiUrl: string;
  adminMode: boolean;
  language: string;
  twinName: string;
  twinAvatarUrl: string;
};

export const appConfig: AppConfig = {
  apiUrl: trimTrailingSlash((import.meta.env.VITE_API_URL ?? "").trim()),
  adminMode: (import.meta.env.VITE_ADMIN_MODE ?? "").trim() === "true",
  language: configuredLanguage,
  twinName:
    (import.meta.env.VITE_TWIN_NAME ?? strings.appTitle).trim() ||
    strings.appTitle,
  twinAvatarUrl: (import.meta.env.VITE_TWIN_AVATAR_URL ?? "").trim(),
};

export const appLanguage = getPrimaryLanguageTag(configuredLanguage);
