import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CatalogFormDialog } from "@/components/CatalogFormDialog";
import * as adminApi from "@/lib/admin-api";

vi.mock("@/lib/admin-api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/admin-api")>("@/lib/admin-api");

  return {
    ...actual,
    getCatalogItem: vi.fn(),
  };
});

const item = {
  id: "catalog-1",
  sku: "BOOK-001",
  name: "AI in Practice",
  description: "A practical book.",
  item_type: "book",
  url: "https://example.com/book",
  image_url: null,
  is_active: true,
  valid_from: null,
  valid_until: null,
  created_at: "2026-03-25T12:00:00Z",
  updated_at: "2026-03-25T12:00:00Z",
  linked_sources_count: 1,
} as const;

describe("CatalogFormDialog", () => {
  beforeEach(() => {
    vi.mocked(adminApi.getCatalogItem).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders create mode and validates required fields", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();

    render(
      <CatalogFormDialog
        editingItem={null}
        isSaving={false}
        onClose={() => {}}
        onSave={onSave}
        open
      />,
    );

    expect(
      screen.getByRole("heading", { name: /add product/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /create/i }));

    expect(screen.getByText(/sku is required/i)).toBeInTheDocument();
    expect(screen.getByText(/name is required/i)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders edit mode and loads linked sources", async () => {
    vi.mocked(adminApi.getCatalogItem).mockResolvedValue({
      ...item,
      linked_sources: [
        {
          id: "source-1",
          title: "Catalog Notes",
          source_type: "markdown",
          status: "ready",
        },
      ],
    });

    render(
      <CatalogFormDialog
        editingItem={item}
        isSaving={false}
        onClose={() => {}}
        onSave={() => {}}
        open
      />,
    );

    expect(screen.getByDisplayValue("BOOK-001")).toBeInTheDocument();
    expect(screen.getByDisplayValue("AI in Practice")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Catalog Notes")).toBeInTheDocument();
    });
  });

  it("submits only changed fields in edit mode", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();

    vi.mocked(adminApi.getCatalogItem).mockResolvedValue({
      ...item,
      linked_sources: [],
    });

    render(
      <CatalogFormDialog
        editingItem={item}
        isSaving={false}
        onClose={() => {}}
        onSave={onSave}
        open
      />,
    );

    const nameInput = screen.getByDisplayValue("AI in Practice");
    await user.clear(nameInput);
    await user.type(nameInput, "AI in Practice 2nd Ed");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(onSave).toHaveBeenCalledWith({ name: "AI in Practice 2nd Ed" });
  });

  it("shows linked sources load errors in edit mode", async () => {
    vi.mocked(adminApi.getCatalogItem).mockRejectedValue(
      new Error("Linked sources failed"),
    );

    render(
      <CatalogFormDialog
        editingItem={item}
        isSaving={false}
        onClose={() => {}}
        onSave={() => {}}
        open
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Linked sources failed")).toBeInTheDocument();
    });
  });
});
