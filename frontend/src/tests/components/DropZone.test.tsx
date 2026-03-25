import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DropZone } from "@/components/DropZone/DropZone";

describe("DropZone", () => {
  it("renders instructions and highlights on drag over", () => {
    const onFiles = vi.fn();
    render(<DropZone onFiles={onFiles} />);

    const zone = screen.getByRole("button", {
      name: /drop files to add new sources/i,
    });

    fireEvent.dragEnter(zone, {
      dataTransfer: { files: [new File(["x"], "note.md")] },
    });

    expect(zone).toHaveAttribute("data-dragging", "true");
  });

  it("passes dropped files to the handler", () => {
    const onFiles = vi.fn();
    render(<DropZone onFiles={onFiles} />);

    const zone = screen.getByRole("button", {
      name: /drop files to add new sources/i,
    });
    const file = new File(["x"], "note.md");

    fireEvent.drop(zone, {
      dataTransfer: { files: [file] },
    });

    expect(onFiles).toHaveBeenCalledWith([file]);
  });
});
