import { describe, expect, it } from "vitest";

import { formatRelativeTime } from "@/lib/strings";

describe("formatRelativeTime", () => {
  it("returns an empty string for invalid dates", () => {
    expect(formatRelativeTime("not-a-date")).toBe("");
  });
});
