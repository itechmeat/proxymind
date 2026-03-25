import { appConfig } from "@/lib/config";

export function getInitials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map(
      (part) =>
        Array.from(part)[0]?.toLocaleUpperCase(appConfig.language) ?? "",
    )
    .join("");
}
