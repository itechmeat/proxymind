import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SourceList } from "@/components/SourceList/SourceList";

const sources = [
  {
    id: "source-1",
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
        deletingSourceId={null}
        onDelete={onDelete}
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
});
