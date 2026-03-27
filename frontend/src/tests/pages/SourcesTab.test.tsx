import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourcesTab } from "@/pages/AdminPage/SourcesTab";

vi.mock("@/hooks/useSources", () => ({
  useSources: vi.fn(),
}));

import { useSources } from "@/hooks/useSources";

describe("SourcesTab", () => {
  beforeEach(() => {
    vi.mocked(useSources).mockReturnValue({
      catalogItems: [
        {
          id: "catalog-1",
          sku: "BOOK-001",
          name: "AI in Practice",
          description: null,
          item_type: "book",
          url: null,
          image_url: null,
          is_active: true,
          valid_from: null,
          valid_until: null,
          created_at: "2026-03-25T12:00:00Z",
          updated_at: "2026-03-25T12:00:00Z",
          linked_sources_count: 0,
        },
      ],
      catalogLoadError: null,
      deletingSourceId: null,
      isLoading: false,
      isRefreshingCatalog: false,
      isUploading: false,
      linkingSourceId: null,
      linkSourceToCatalog: vi.fn(),
      refreshCatalogItems: vi.fn(),
      refreshSources: vi.fn(),
      removeSource: vi.fn(),
      sources: [],
      uploadFiles: vi.fn(),
    });
  });

  it("renders the upload product dropdown outside the drop zone", () => {
    render(<SourcesTab />);

    const dropZoneButton = screen.getByRole("button", {
      name: /drop files to add new sources/i,
    });
    const uploadProductSelect = screen.getByRole("combobox", {
      name: /link to product/i,
    });

    expect(dropZoneButton.contains(uploadProductSelect)).toBe(false);
    expect(uploadProductSelect).toBeInTheDocument();
  });

  it("shows retry controls when the catalog product list fails to load", () => {
    const refreshCatalogItems = vi.fn();

    vi.mocked(useSources).mockReturnValue({
      catalogItems: [],
      catalogLoadError: "Failed to load products",
      deletingSourceId: null,
      isLoading: false,
      isRefreshingCatalog: false,
      isUploading: false,
      linkingSourceId: null,
      linkSourceToCatalog: vi.fn(),
      refreshCatalogItems,
      refreshSources: vi.fn(),
      removeSource: vi.fn(),
      sources: [],
      uploadFiles: vi.fn(),
    });

    render(<SourcesTab />);

    expect(
      screen.getByRole("combobox", { name: /link to product/i }),
    ).toHaveValue("__load_failed__");
    expect(screen.getByRole("button", { name: /retry loading products/i }));
  });
});
