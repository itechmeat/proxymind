import { render, screen } from "@testing-library/react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { describe, expect, it } from "vitest";

import { citationSanitizeSchema } from "@/lib/citation-markdown";
import { remarkCitations } from "@/lib/remark-citations";
import type { CitationResponse } from "@/types/chat";

const citations: CitationResponse[] = [
  {
    index: 1,
    source_id: "source-1",
    source_title: "Source 1",
    source_type: "html",
    url: "https://example.com/source-1",
    anchor: {
      page: null,
      chapter: null,
      section: null,
      timecode: null,
    },
    text_citation: "Excerpt 1",
  },
  {
    index: 2,
    source_id: "source-2",
    source_title: "Source 2",
    source_type: "pdf",
    url: null,
    anchor: {
      page: 4,
      chapter: null,
      section: null,
      timecode: null,
    },
    text_citation: "Excerpt 2",
  },
];

function renderMarkdown(
  value: string,
  options?: {
    citations?: CitationResponse[] | null;
    enabled?: boolean;
  },
) {
  return render(
    <ReactMarkdown
      rehypePlugins={[rehypeRaw, [rehypeSanitize, citationSanitizeSchema]]}
      remarkPlugins={[
        [
          remarkCitations,
          {
            citations: options?.citations ?? citations,
            enabled: options?.enabled ?? true,
          },
        ],
      ]}
    >
      {value}
    </ReactMarkdown>,
  );
}

describe("remarkCitations", () => {
  it("replaces valid markers with citation buttons", () => {
    renderMarkdown("Alpha [source:1] omega");

    const button = screen.getByRole("button", { name: "Jump to source 1" });

    expect(button).toHaveTextContent("1");
    expect(screen.queryByText("[source:1]")).not.toBeInTheDocument();
  });

  it("replaces multiple markers in the same paragraph", () => {
    renderMarkdown("One [source:1] and two [source:2]");

    expect(
      screen.getByRole("button", { name: "Jump to source 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Jump to source 2" }),
    ).toBeInTheDocument();
  });

  it("keeps out-of-range markers as plain text", () => {
    renderMarkdown("Missing [source:99] citation");

    expect(
      screen.getByText("Missing [source:99] citation"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("is a no-op when no markers are present", () => {
    renderMarkdown("Plain markdown content");

    expect(screen.getByText("Plain markdown content")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps markers as plain text when citations are empty", () => {
    renderMarkdown("No data [source:1]", {
      citations: [],
    });

    expect(screen.getByText("No data [source:1]")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not transform markers when disabled", () => {
    renderMarkdown("User text [source:1]", {
      enabled: false,
    });

    expect(screen.getByText("User text [source:1]")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
