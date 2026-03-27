import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CatalogList } from "@/components/CatalogList";

const items = [
  {
    id: "catalog-1",
    sku: "BOOK-001",
    name: "AI in Practice",
    description: "A practical book.",
    item_type: "book",
    url: null,
    image_url: null,
    is_active: true,
    valid_from: null,
    valid_until: null,
    created_at: "2026-03-25T12:00:00Z",
    updated_at: "2026-03-25T12:00:00Z",
    linked_sources_count: 2,
  },
] as const;

describe("CatalogList", () => {
  it("renders item rows and empty state", () => {
    const { rerender } = render(
      <CatalogList
        deletingItemId={null}
        filterType={null}
        items={[...items]}
        onDelete={() => {}}
        onEdit={() => {}}
      />,
    );

    expect(screen.getAllByText("AI in Practice")).toHaveLength(2);
    expect(screen.getAllByText("BOOK-001")).toHaveLength(2);
    expect(screen.getAllByText(/2 linked/i)).toHaveLength(2);

    rerender(
      <CatalogList
        deletingItemId={null}
        filterType={null}
        items={[]}
        onDelete={() => {}}
        onEdit={() => {}}
      />,
    );

    expect(screen.getByText(/no products yet/i)).toBeInTheDocument();
  });

  it("opens delete confirmation and confirms deletion", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();

    render(
      <CatalogList
        deletingItemId={null}
        filterType={null}
        items={[...items]}
        onDelete={onDelete}
        onEdit={() => {}}
      />,
    );

    const [deleteButton] = screen.getAllByRole("button", {
      name: /delete product ai in practice/i,
    });

    expect(deleteButton).toBeDefined();

    if (!deleteButton) {
      throw new Error("Delete button not found");
    }

    await user.click(deleteButton);

    expect(screen.getByText(/will be deactivated/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /delete product/i }));

    expect(onDelete).toHaveBeenCalledWith(items[0]);
  });

  it("shows the filtered empty state and forwards edit actions", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const { rerender } = render(
      <CatalogList
        deletingItemId={null}
        filterType={null}
        items={[...items]}
        onDelete={() => {}}
        onEdit={onEdit}
      />,
    );

    const [editButton] = screen.getAllByRole("button", {
      name: /edit product ai in practice/i,
    });

    if (!editButton) {
      throw new Error("Edit button not found");
    }

    await user.click(editButton);

    expect(onEdit).toHaveBeenCalledWith(items[0]);

    rerender(
      <CatalogList
        deletingItemId={null}
        filterType="book"
        items={[]}
        onDelete={() => {}}
        onEdit={() => {}}
      />,
    );

    expect(
      screen.getByText(/no products match the selected type/i),
    ).toBeInTheDocument();
  });
});
