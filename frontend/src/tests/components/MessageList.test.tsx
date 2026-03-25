import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageList } from "@/components/MessageList";
import { strings } from "@/lib/strings";
import type { ChatMessage } from "@/types/chat";

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

describe("MessageList", () => {
  it("renders the message list", () => {
    render(
      <MessageList
        messages={[
          createMessage(),
          createMessage({
            id: "message-2",
            role: "user",
            parts: [{ type: "text", text: "Second" }],
          }),
        ]}
        twinName="ProxyMind"
      />,
    );

    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  it("renders the empty state", () => {
    render(<MessageList messages={[]} twinName="ProxyMind" />);

    expect(screen.getByText(strings.emptyStateTitle)).toBeInTheDocument();
    expect(screen.getByText(strings.emptyStateBody)).toBeInTheDocument();
  });

  it("renders a scroll container", () => {
    render(<MessageList messages={[createMessage()]} twinName="ProxyMind" />);

    expect(
      screen.getByLabelText(strings.conversationLabel),
    ).toBeInTheDocument();
  });

  it("shows the scroll-to-bottom button when scrolled up", () => {
    render(
      <MessageList
        messages={[
          createMessage(),
          createMessage({
            id: "message-2",
            parts: [{ type: "text", text: "Second" }],
          }),
        ]}
        twinName="ProxyMind"
      />,
    );

    const viewport = document.querySelector<HTMLElement>(
      "[data-slot='scroll-area-viewport']",
    );

    if (!viewport) {
      throw new Error("Viewport not found");
    }

    Object.defineProperty(viewport, "clientHeight", {
      configurable: true,
      value: 100,
    });
    Object.defineProperty(viewport, "scrollHeight", {
      configurable: true,
      value: 400,
    });
    Object.defineProperty(viewport, "scrollTop", {
      configurable: true,
      value: 10,
      writable: true,
    });

    fireEvent.scroll(viewport);

    expect(
      screen.getByRole("button", { name: strings.scrollToBottom }),
    ).toBeInTheDocument();
  });
});
