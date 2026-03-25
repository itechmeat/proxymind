import {
  FileText,
  FileType,
  Globe,
  Headphones,
  ImageIcon,
  Video,
} from "lucide-react";
import { describe, expect, it } from "vitest";

import { getSourceIcon } from "@/lib/source-icons";

describe("getSourceIcon", () => {
  it.each([
    ["pdf", FileText, "#ef4444"],
    ["docx", FileText, "#6b7280"],
    ["markdown", FileType, "#6b7280"],
    ["txt", FileType, "#6b7280"],
    ["html", Globe, "#3b82f6"],
    ["image", ImageIcon, "#10b981"],
    ["audio", Headphones, "#f59e0b"],
    ["video", Video, "#a855f7"],
  ])("maps %s to the expected icon and color", (sourceType, Icon, color) => {
    const result = getSourceIcon(sourceType);

    expect(result.Icon).toBe(Icon);
    expect(result.color).toBe(color);
  });

  it("falls back to FileText and gray for unknown source types", () => {
    const result = getSourceIcon("spreadsheet");

    expect(result.Icon).toBe(FileText);
    expect(result.color).toBe("#6b7280");
  });
});
