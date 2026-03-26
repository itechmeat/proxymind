import { appConfig } from "@/lib/config";

function toSafeLocaleUppercase(value: string, locale: string) {
  try {
    return value.toLocaleUpperCase(locale);
  } catch {
    return value.toUpperCase();
  }
}

export function getInitials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => {
      const initial = Array.from(part)[0];
      return initial ? toSafeLocaleUppercase(initial, appConfig.language) : "";
    })
    .join("");
}
