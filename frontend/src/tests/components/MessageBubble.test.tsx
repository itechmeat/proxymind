import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MessageBubble } from "@/components/MessageBubble";
import { strings } from "@/lib/strings";
import type { ChatMessage, CitationResponse } from "@/types/chat";

function createMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "message-1",
    role: "assistant",
    metadata: {
      createdAt: "2026-03-25T11:55:00Z",
      state: "complete",
    },
    parts: [{ type: "text", text: "Hello" }],
    ...overrides,
  };
}

function createCitation(
  index: number,
  overrides: Partial<CitationResponse> = {},
): CitationResponse {
  return {
    index,
    source_id: `source-${index}`,
    source_title: `Source ${index}`,
    source_type: "html",
    url: `https://example.com/source-${index}`,
    anchor: {
      page: null,
      chapter: null,
      section: null,
      timecode: null,
    },
    text_citation: `Excerpt ${index}`,
    ...overrides,
  };
}

describe("MessageBubble", () => {
  it("renders a user message as plain text", () => {
    render(
      <MessageBubble
        message={createMessage({
          role: "user",
          parts: [{ type: "text", text: "Hello user" }],
        })}
        twinName="ProxyMind"
      />,
    );

    expect(screen.getByText("Hello user")).toBeInTheDocument();
  });

  it("renders assistant markdown content", () => {
    render(
      <MessageBubble
        message={createMessage({
          parts: [{ type: "text", text: "**Bold** response" }],
        })}
        twinName="ProxyMind"
      />,
    );

    expect(screen.getByText("Bold").closest("strong")).not.toBeNull();
  });

  it("shows retry button on failed messages", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();

    render(
      <MessageBubble
        message={createMessage({
          metadata: {
            createdAt: "2026-03-25T11:55:00Z",
            state: "failed",
            errorDetail: strings.connectionLost,
          },
        })}
        onRetry={onRetry}
        twinName="ProxyMind"
      />,
    );

    await user.click(screen.getByRole("button", { name: strings.retry }));

    expect(onRetry).toHaveBeenCalledWith("message-1");
  });

  it("shows incomplete indicator for partial messages", () => {
    render(
      <MessageBubble
        message={createMessage({
          metadata: {
            createdAt: "2026-03-25T11:55:00Z",
            state: "partial",
          },
        })}
        twinName="ProxyMind"
      />,
    );

    expect(screen.getByText(strings.incomplete)).toBeInTheDocument();
  });

  it("shows the streaming indicator for streaming messages", () => {
    render(
      <MessageBubble
        message={createMessage({
          metadata: {
            createdAt: "2026-03-25T11:55:00Z",
            state: "streaming",
          },
        })}
        twinName="ProxyMind"
      />,
    );

    expect(screen.getByLabelText(strings.streamingLabel)).toBeInTheDocument();
  });

  it("renders relative timestamps", () => {
    render(
      <MessageBubble
        message={createMessage()}
        now={new Date("2026-03-25T12:00:00Z")}
        twinName="ProxyMind"
      />,
    );

    const timestamp = screen.getByText("5m ago");

    expect(timestamp).toBeInTheDocument();
    expect(timestamp.closest("time")).toHaveAttribute(
      "dateTime",
      "2026-03-25T11:55:00Z",
    );
  });

  it("renders citations and preserves raw message text", () => {
    const message = createMessage({
      metadata: {
        createdAt: "2026-03-25T11:55:00Z",
        citations: [createCitation(1)],
        state: "complete",
      },
      parts: [{ type: "text", text: "Answer [source:1]" }],
    });
    const originalParts = structuredClone(message.parts);

    render(<MessageBubble message={message} twinName="ProxyMind" />);

    expect(
      screen.getByRole("button", { name: "Jump to source 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sources (1)" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("[source:1]")).not.toBeInTheDocument();
    expect(message.parts).toEqual(originalParts);
  });

  it("does not render the citations block when citations are absent", () => {
    render(
      <MessageBubble
        message={createMessage({
          metadata: {
            createdAt: "2026-03-25T11:55:00Z",
            citations: [],
            state: "complete",
          },
          parts: [{ type: "text", text: "Answer without citations" }],
        })}
        twinName="ProxyMind"
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Sources (0)" }),
    ).not.toBeInTheDocument();
  });

  it("keeps raw citation markers and hides sources while streaming", () => {
    render(
      <MessageBubble
        message={createMessage({
          metadata: {
            createdAt: "2026-03-25T11:55:00Z",
            citations: [createCitation(1)],
            state: "streaming",
          },
          parts: [{ type: "text", text: "Streaming [source:1]" }],
        })}
        twinName="ProxyMind"
      />,
    );

    expect(screen.getByText("Streaming [source:1]")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Jump to source 1" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sources (1)" }),
    ).not.toBeInTheDocument();
  });

  it("expands and highlights the matching source item when a citation is clicked", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();

    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    render(
      <MessageBubble
        message={createMessage({
          metadata: {
            createdAt: "2026-03-25T11:55:00Z",
            citations: [
              createCitation(1, { source_title: "HTML source" }),
              createCitation(2, {
                source_title: "PDF source",
                source_type: "pdf",
                url: null,
              }),
            ],
            state: "complete",
          },
          parts: [{ type: "text", text: "Answer [source:2]" }],
        })}
        twinName="ProxyMind"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Jump to source 2" }));

    const toggle = screen.getByRole("button", { name: "Sources (2)" });
    const sourceItem = (await screen.findByText("PDF source")).closest("li");

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(sourceItem).toHaveAttribute("data-highlighted", "true");
    expect(scrollIntoView).toHaveBeenCalled();
  });
});
