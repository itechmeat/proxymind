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

    expect(getInitials("istanbul izmir")).toBe("İİ");

    appConfig.language = originalLanguage;
    vi.unstubAllGlobals();
  });
});
