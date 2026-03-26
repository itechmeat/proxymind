import { describe, expect, it, vi } from "vitest";

import { appConfig } from "@/lib/config";
import { getInitials } from "@/lib/identity";

describe("getInitials", () => {
  it("uses locale-aware uppercase rules", () => {
    const originalLanguage = appConfig.language;

    vi.stubGlobal("navigator", {
      language: "tr",
    });

    appConfig.language = "tr";

    try {
      expect(getInitials("istanbul izmir")).toBe("İİ");
    } finally {
      appConfig.language = originalLanguage;
      vi.unstubAllGlobals();
    }
  });

  it("falls back safely when the configured locale is invalid", () => {
    const originalLanguage = appConfig.language;
    appConfig.language = "en_US";

    try {
      expect(getInitials("proxy mind")).toBe("PM");
    } finally {
      appConfig.language = originalLanguage;
    }
  });
});
