import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CitationsBlock } from "@/components/CitationsBlock";
import type { CitationResponse } from "@/types/chat";

const citations: CitationResponse[] = [
  {
    index: 1,
    source_id: "source-1",
    source_title: "Live HTML source",
    source_type: "html",
    url: "https://example.com/source-1",
    anchor: {
      page: null,
      chapter: null,
      section: null,
      timecode: null,
    },
    text_citation: "HTML excerpt",
  },
  {
    index: 2,
    source_id: "source-2",
    source_title: "Offline PDF source",
    source_type: "pdf",
    url: null,
    anchor: {
      page: 3,
      chapter: null,
      section: null,
      timecode: null,
    },
    text_citation: "PDF excerpt",
  },
  {
    index: 3,
    source_id: "source-3",
    source_title: "Image source",
    source_type: "image",
    url: "https://example.com/image.png",
    anchor: {
      page: null,
      chapter: null,
      section: null,
      timecode: null,
    },
    text_citation: "Image excerpt",
  },
];

describe("CitationsBlock", () => {
  it("does not render when citations are empty", () => {
    const { container } = render(
      <CitationsBlock citations={[]} expanded={false} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders collapsed by default", () => {
    render(<CitationsBlock citations={citations} expanded={false} />);

    expect(screen.getByRole("button", { name: "Sources (3)" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("Live HTML source")).not.toBeInTheDocument();
  });

  it("renders online sources as external links when expanded", () => {
    render(<CitationsBlock citations={citations} expanded />);

    expect(
      screen.getByRole("link", { name: "Live HTML source" }),
    ).toHaveAttribute("href", "https://example.com/source-1");
    expect(
      screen.getByRole("link", { name: "Live HTML source" }),
    ).toHaveAttribute("target", "_blank");
  });

  it("renders offline sources as plain text when expanded", () => {
    render(<CitationsBlock citations={citations} expanded />);

    expect(screen.getByText("Offline PDF source").closest("a")).toBeNull();
  });

  it("renders the citation index inside each source item", () => {
    render(<CitationsBlock citations={citations} expanded />);

    const sourceItem = screen.getByText("Live HTML source").closest("li");

    expect(sourceItem).not.toBeNull();
    if (!sourceItem) {
      throw new Error("Expected citation list item to be rendered");
    }

    expect(within(sourceItem).getByText("1")).toHaveClass(
      "citations-block__index",
    );
  });

  it("calls onImageClick for image sources", async () => {
    const user = userEvent.setup();
    const onImageClick = vi.fn();

    render(
      <CitationsBlock
        citations={citations}
        expanded
        onImageClick={onImageClick}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Image source" }));

    expect(onImageClick).toHaveBeenCalledWith(citations[2]);
  });

  it("toggles between collapsed and expanded states", async () => {
    const user = userEvent.setup();
    const onExpandedChange = vi.fn();

    const { rerender } = render(
      <CitationsBlock
        citations={citations}
        expanded={false}
        onExpandedChange={onExpandedChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Sources (3)" }));

    expect(onExpandedChange).toHaveBeenCalledWith(true);

    rerender(
      <CitationsBlock
        citations={citations}
        expanded
        onExpandedChange={onExpandedChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Sources (3)" }));

    expect(onExpandedChange).toHaveBeenLastCalledWith(false);
  });
});
