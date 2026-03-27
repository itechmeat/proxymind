import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceList } from "@/components/SourceList/SourceList";

const sources = [
  {
    id: "source-1",
    catalog_item_id: null,
    title: "Marcus Notes",
    source_type: "markdown",
    status: "ready",
    description: null,
    public_url: null,
    file_size_bytes: 100,
    language: "en",
    created_at: "2026-03-25T12:00:00Z",
  },
] as const;

describe("SourceList", () => {
  it("opens a delete confirmation and confirms deletion", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();

    render(
      <SourceList
        catalogItems={[]}
        catalogLoadError={null}
        deletingSourceId={null}
        linkingSourceId={null}
        onDelete={onDelete}
        onLinkCatalogItem={() => {}}
        sources={[...sources]}
      />,
    );

    const [deleteButton] = screen.getAllByRole("button", {
      name: /delete marcus notes/i,
    });

    expect(deleteButton).toBeDefined();

    if (!deleteButton) {
      throw new Error("Delete button not found");
    }

    await user.click(deleteButton);

    expect(
      screen.getByText(/chunks in published snapshots will remain/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/chunks in published snapshots will remain/i),
    ).not.toBeInTheDocument();

    await user.click(deleteButton);

    await user.click(screen.getByRole("button", { name: /delete source/i }));

    expect(onDelete).toHaveBeenCalledWith(sources[0]);
  });

  it("renders product dropdown and supports stale reference fallback", async () => {
    const onLinkCatalogItem = vi.fn();

    render(
      <SourceList
        catalogItems={[]}
        catalogLoadError={null}
        deletingSourceId={null}
        linkingSourceId={null}
        onDelete={() => {}}
        onLinkCatalogItem={onLinkCatalogItem}
        sources={[
          {
            ...sources[0],
            catalog_item_id: "catalog-stale",
          },
        ]}
      />,
    );

    const [select] = screen.getAllByRole("combobox", {
      name: /link to product marcus notes/i,
    });

    expect(select).toBeDefined();

    if (!select) {
      throw new Error("Product select not found");
    }

    expect(select).toHaveValue("catalog-stale");
    expect(
      screen.getAllByRole("option", { name: /unknown product/i }),
    ).toHaveLength(2);
  });

  it("allows unlinking a product from a source", async () => {
    const user = userEvent.setup();
    const onLinkCatalogItem = vi.fn();

    render(
      <SourceList
        catalogItems={[
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
            linked_sources_count: 1,
          },
        ]}
        catalogLoadError={null}
        deletingSourceId={null}
        linkingSourceId={null}
        onDelete={() => {}}
        onLinkCatalogItem={onLinkCatalogItem}
        sources={[
          {
            ...sources[0],
            catalog_item_id: "catalog-1",
          },
        ]}
      />,
    );

    const [select] = screen.getAllByRole("combobox", {
      name: /link to product marcus notes/i,
    });

    if (!select) {
      throw new Error("Product select not found");
    }

    await user.selectOptions(select, "");

    expect(onLinkCatalogItem).toHaveBeenCalledWith("source-1", null);
  });

  it("shows a disabled load failure option when catalog products fail to load", () => {
    render(
      <SourceList
        catalogItems={[]}
        catalogLoadError="Failed to load products"
        deletingSourceId={null}
        linkingSourceId={null}
        onDelete={() => {}}
        onLinkCatalogItem={() => {}}
        sources={[...sources]}
      />,
    );

    const [select] = screen.getAllByRole("combobox", {
      name: /link to product marcus notes/i,
    });

    expect(select).toHaveValue("__load_failed__");
    expect(
      screen.getAllByRole("option", { name: /failed to load products/i }),
    ).toHaveLength(2);
  });
});
