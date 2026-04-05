import { delay, HttpResponse, http } from "msw";

import {
  MOCK_SESSION_ID,
  MOCK_SNAPSHOT_ID,
  mockResponses,
} from "@/mocks/data/fixtures";

function sseBlock(event: string, data: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

let responseIndex = 0;

export function resetMessageHandlersState() {
  responseIndex = 0;
}

export const messageHandlers = [
  http.post("*/api/chat/messages", async () => {
    const messageId = crypto.randomUUID();
    const encoder = new TextEncoder();

    const variant = mockResponses[responseIndex % mockResponses.length];
    responseIndex += 1;

    // Simulate reasoning delay (1–2 seconds)
    await delay(randomInt(1000, 2000));

    const chunks: Uint8Array[] = [];

    chunks.push(
      encoder.encode(
        sseBlock("meta", {
          message_id: messageId,
          session_id: MOCK_SESSION_ID,
          snapshot_id: MOCK_SNAPSHOT_ID,
        }),
      ),
    );

    for (const token of variant.tokens) {
      chunks.push(encoder.encode(sseBlock("token", { content: token })));
    }

    if (variant.citations.length > 0) {
      chunks.push(
        encoder.encode(sseBlock("citations", { citations: variant.citations })),
      );
    }

    chunks.push(
      encoder.encode(
        sseBlock("done", {
          token_count_prompt: randomInt(200, 500),
          token_count_completion: variant.tokens.length,
          model_name: "mock-model",
          retrieved_chunks_count: randomInt(3, 8),
        }),
      ),
    );

    const body = new Blob(chunks as BlobPart[]).stream();

    return new HttpResponse(body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
    });
  }),
];
