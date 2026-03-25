import { describe, expect, it } from "vitest";

import { toUIMessages } from "@/lib/message-adapter";
import type { MessageInHistory } from "@/types/chat";

function createHistoryMessage(
  overrides: Partial<MessageInHistory> = {},
): MessageInHistory {
  return {
    id: "message-1",
    role: "assistant",
    content: "Hello world",
    status: "complete",
    citations: null,
    model_name: "gemini-test",
    created_at: "2026-03-25T12:00:00Z",
    ...overrides,
  };
}

describe("toUIMessages", () => {
  it("converts a complete assistant message", () => {
    const [message] = toUIMessages([createHistoryMessage()]);

    expect(message).toMatchObject({
      id: "message-1",
      role: "assistant",
      metadata: {
        modelName: "gemini-test",
        state: "complete",
      },
      parts: [{ type: "text", text: "Hello world", state: "done" }],
    });
  });

  it("maps received status to complete", () => {
    const [message] = toUIMessages([
      createHistoryMessage({
        role: "user",
        status: "received",
        model_name: null,
      }),
    ]);

    expect(message.metadata?.state).toBe("complete");
    expect(message.role).toBe("user");
  });

  it("preserves partial status", () => {
    const [message] = toUIMessages([
      createHistoryMessage({
        status: "partial",
        content: "Incomplete response",
      }),
    ]);

    expect(message.metadata?.state).toBe("partial");
    expect(message.parts[0]).toMatchObject({
      type: "text",
      text: "Incomplete response",
      state: "done",
    });
  });

  it("maps streaming history to partial state", () => {
    const [message] = toUIMessages([
      createHistoryMessage({
        status: "streaming",
        content: "Recovered partial output",
      }),
    ]);

    expect(message.metadata?.state).toBe("partial");
    expect(message.parts[0]).toMatchObject({
      type: "text",
      text: "Recovered partial output",
      state: "done",
    });
  });

  it("preserves failed status", () => {
    const [message] = toUIMessages([
      createHistoryMessage({
        status: "failed",
        content: "Partial text",
      }),
    ]);

    expect(message.metadata?.state).toBe("failed");
    expect(message.parts[0]).toMatchObject({
      type: "text",
      text: "Partial text",
      state: "done",
    });
  });

  it("preserves citations in metadata", () => {
    const [message] = toUIMessages([
      createHistoryMessage({
        citations: [
          {
            index: 1,
            source_id: "source-1",
            source_title: "Doc",
            source_type: "pdf",
            url: null,
            anchor: {
              page: 1,
              chapter: null,
              section: null,
              timecode: null,
            },
            text_citation: "Doc, p. 1",
          },
        ],
      }),
    ]);

    expect(message.metadata?.citations).toEqual([
      expect.objectContaining({
        source_id: "source-1",
        source_title: "Doc",
      }),
    ]);
  });

  it("returns an empty array for empty history", () => {
    expect(toUIMessages([])).toEqual([]);
  });
});
