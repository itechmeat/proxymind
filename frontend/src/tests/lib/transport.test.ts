import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildApiUrl } from "@/lib/api";
import { strings } from "@/lib/strings";
import { ProxyMindTransport } from "@/lib/transport";
import type { ChatMessage } from "@/types/chat";

const fetchMock = vi.fn<typeof fetch>();

function createAccessTokenGetter(accessToken = "access-token") {
  return vi
    .fn<(options?: { forceRefresh?: boolean }) => Promise<string | null>>()
    .mockResolvedValue(accessToken);
}

function createUserMessage(text: string, id = "user-1"): ChatMessage {
  return {
    id,
    role: "user",
    parts: [{ type: "text", text }],
  };
}

function streamFromChunks(chunks: string[]) {
  const encoder = new TextEncoder();

  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

function sseResponse(chunks: string[], status = 200) {
  return new Response(streamFromChunks(chunks), {
    status,
    headers: {
      "Content-Type": "text/event-stream",
    },
  });
}

function jsonResponse(body: unknown, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

async function readChunks(stream: ReadableStream<unknown>) {
  const reader = stream.getReader();
  const chunks: unknown[] = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    chunks.push(value);
  }

  return chunks;
}

describe("ProxyMindTransport", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("posts backend payload, maps SSE to UI chunks, and handles citations sideband", async () => {
    const onCitations = vi.fn();
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("fallback-message-id")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
        'event: token\ndata: {"content":"Hello"}\n\n',
        'event: citations\ndata: {"citations":[{"index":1,"source_id":"source-1","source_title":"Doc","source_type":"pdf","url":null,"anchor":{"page":1,"chapter":null,"section":null,"timecode":null},"text_citation":"Doc, p. 1"}]}\n\n',
        'event: done\ndata: {"token_count_prompt":11,"token_count_completion":7,"model_name":"gemini-test","retrieved_chunks_count":4}\n\n',
      ]),
    );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
      onCitations,
    });

    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "chat-1",
      messageId: undefined,
      messages: [createUserMessage("Hello")],
      abortSignal: undefined,
    });

    const chunks = await readChunks(stream);
    const request = fetchMock.mock.calls[0];
    const body = JSON.parse(String(request[1]?.body));

    expect(request[0]).toBe(buildApiUrl("/api/chat/messages"));
    expect(request[1]?.headers).toEqual({
      Authorization: "Bearer access-token",
      "Content-Type": "application/json",
    });
    expect(body).toEqual({
      session_id: "session-1",
      text: "Hello",
      idempotency_key: "idempotency-key",
    });
    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-1",
        messageMetadata: {
          sessionId: "session-1",
          snapshotId: "snapshot-1",
          state: "streaming",
        },
      },
      { type: "text-start", id: "text-part-id" },
      { type: "text-delta", id: "text-part-id", delta: "Hello" },
      {
        type: "message-metadata",
        messageMetadata: {
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
        },
      },
      { type: "text-end", id: "text-part-id" },
      {
        type: "finish",
        finishReason: "stop",
        messageMetadata: {
          modelName: "gemini-test",
          retrievedChunksCount: 4,
          tokenCountPrompt: 11,
          tokenCountCompletion: 7,
          state: "complete",
        },
      },
    ]);
    expect(onCitations).toHaveBeenCalledWith({
      messageId: "assistant-1",
      citations: [
        expect.objectContaining({
          source_id: "source-1",
          source_title: "Doc",
        }),
      ],
    });
  });

  it("generates a new idempotency key for each send", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("fallback-1")
      .mockReturnValueOnce("key-1")
      .mockReturnValueOnce("text-1")
      .mockReturnValueOnce("fallback-2")
      .mockReturnValueOnce("key-2")
      .mockReturnValueOnce("text-2");

    fetchMock
      .mockResolvedValueOnce(
        sseResponse([
          'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
          'event: done\ndata: {"token_count_prompt":1,"token_count_completion":1,"model_name":"gemini-test","retrieved_chunks_count":1}\n\n',
        ]),
      )
      .mockResolvedValueOnce(
        sseResponse([
          'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
          'event: done\ndata: {"token_count_prompt":1,"token_count_completion":1,"model_name":"gemini-test","retrieved_chunks_count":1}\n\n',
        ]),
      );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("First", "user-1")],
        abortSignal: undefined,
      }),
    );
    await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Second", "user-2")],
        abortSignal: undefined,
      }),
    );

    const firstBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    const secondBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));

    expect(firstBody.idempotency_key).toBe("key-1");
    expect(secondBody.idempotency_key).toBe("key-2");
  });

  it("surfaces HTTP 409 as an error stream", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("assistant-local")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Concurrent stream active" }, 409),
    );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-local",
        messageMetadata: {
          state: "failed",
          errorDetail: "Concurrent stream active",
          httpStatus: 409,
        },
      },
      {
        type: "error",
        errorText: "Concurrent stream active",
      },
    ]);
  });

  it("surfaces HTTP 422 as an error stream", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("assistant-local")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "No active snapshot available" }, 422),
    );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-local",
        messageMetadata: {
          state: "failed",
          errorDetail: "No active snapshot available",
          httpStatus: 422,
        },
      },
      {
        type: "error",
        errorText: "No active snapshot available",
      },
    ]);
  });

  it("does not invalidate the session for non-ownership HTTP 403 errors", async () => {
    const onSessionInvalidated = vi.fn();
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("assistant-local")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "User account is blocked" }, 403),
    );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
      onSessionInvalidated,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(onSessionInvalidated).not.toHaveBeenCalled();
    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-local",
        messageMetadata: {
          state: "failed",
          errorDetail: "User account is blocked",
          httpStatus: 403,
        },
      },
      {
        type: "error",
        errorText: "User account is blocked",
      },
    ]);
  });

  it("invalidates the session for ownership HTTP 403 errors", async () => {
    const onSessionInvalidated = vi.fn();
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("assistant-local")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Session belongs to a different user" }, 403),
    );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
      onSessionInvalidated,
    });

    await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(onSessionInvalidated).toHaveBeenCalledTimes(1);
  });

  it("surfaces network failures as a connection-lost error stream", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("assistant-local")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-local",
        messageMetadata: {
          state: "failed",
          errorDetail: strings.connectionLost,
          httpStatus: null,
        },
      },
      {
        type: "error",
        errorText: strings.connectionLost,
      },
    ]);
  });

  it("stops on an SSE mid-stream error and preserves partial content", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("fallback-message-id")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
        'event: token\ndata: {"content":"Partial"}\n\n',
        'event: error\ndata: {"detail":"LLM response timed out"}\n\n',
      ]),
    );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-1",
        messageMetadata: {
          sessionId: "session-1",
          snapshotId: "snapshot-1",
          state: "streaming",
        },
      },
      { type: "text-start", id: "text-part-id" },
      { type: "text-delta", id: "text-part-id", delta: "Partial" },
      { type: "text-end", id: "text-part-id" },
      {
        type: "message-metadata",
        messageMetadata: {
          state: "failed",
          errorDetail: "LLM response timed out",
        },
      },
      {
        type: "error",
        errorText: "LLM response timed out",
      },
    ]);
  });

  it("retries a dropped stream without duplicating overlapping tokens", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("fallback-message-id")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock
      .mockResolvedValueOnce(
        sseResponse([
          'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
          'event: token\ndata: {"content":"Hel"}\n\n',
        ]),
      )
      .mockResolvedValueOnce(
        sseResponse([
          'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
          'event: token\ndata: {"content":"Hel"}\n\n',
          'event: token\ndata: {"content":"lo"}\n\n',
          'event: done\ndata: {"token_count_prompt":3,"token_count_completion":2,"model_name":"gemini-test","retrieved_chunks_count":1}\n\n',
        ]),
      );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-1",
        messageMetadata: {
          sessionId: "session-1",
          snapshotId: "snapshot-1",
          state: "streaming",
        },
      },
      { type: "text-start", id: "text-part-id" },
      { type: "text-delta", id: "text-part-id", delta: "Hel" },
      {
        type: "message-metadata",
        messageMetadata: {
          sessionId: "session-1",
          snapshotId: "snapshot-1",
          state: "streaming",
        },
      },
      { type: "text-delta", id: "text-part-id", delta: "lo" },
      { type: "text-end", id: "text-part-id" },
      {
        type: "finish",
        finishReason: "stop",
        messageMetadata: {
          modelName: "gemini-test",
          retrievedChunksCount: 1,
          tokenCountPrompt: 3,
          tokenCountCompletion: 2,
          state: "complete",
        },
      },
    ]);

    const firstBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    const secondBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));

    expect(firstBody.idempotency_key).toBe("idempotency-key");
    expect(secondBody.idempotency_key).toBe("idempotency-key");
  });

  it("surfaces connection lost when the retry stream also closes", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("fallback-message-id")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock
      .mockResolvedValueOnce(
        sseResponse([
          'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
          'event: token\ndata: {"content":"Partial"}\n\n',
        ]),
      )
      .mockResolvedValueOnce(
        sseResponse([
          'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
          'event: token\ndata: {"content":"Partial"}\n\n',
        ]),
      );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(chunks).toEqual([
      {
        type: "start",
        messageId: "assistant-1",
        messageMetadata: {
          sessionId: "session-1",
          snapshotId: "snapshot-1",
          state: "streaming",
        },
      },
      { type: "text-start", id: "text-part-id" },
      { type: "text-delta", id: "text-part-id", delta: "Partial" },
      {
        type: "message-metadata",
        messageMetadata: {
          sessionId: "session-1",
          snapshotId: "snapshot-1",
          state: "streaming",
        },
      },
      { type: "text-end", id: "text-part-id" },
      {
        type: "message-metadata",
        messageMetadata: {
          state: "failed",
          errorDetail: strings.connectionLost,
          httpStatus: null,
        },
      },
      {
        type: "error",
        errorText: strings.connectionLost,
      },
    ]);
  });

  it("surfaces connection lost when reconnect receives an HTTP error", async () => {
    const generateId = vi
      .fn<() => string>()
      .mockReturnValueOnce("fallback-message-id")
      .mockReturnValueOnce("idempotency-key")
      .mockReturnValueOnce("text-part-id");

    fetchMock
      .mockResolvedValueOnce(
        sseResponse([
          'event: meta\ndata: {"message_id":"assistant-1","session_id":"session-1","snapshot_id":"snapshot-1"}\n\n',
          'event: token\ndata: {"content":"Partial"}\n\n',
        ]),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Service unavailable" }, 503),
      );

    const transport = new ProxyMindTransport({
      getAccessToken: createAccessTokenGetter(),
      sessionId: "session-1",
      fetch: fetchMock,
      generateId,
    });

    const chunks = await readChunks(
      await transport.sendMessages({
        trigger: "submit-message",
        chatId: "chat-1",
        messageId: undefined,
        messages: [createUserMessage("Hello")],
        abortSignal: undefined,
      }),
    );

    expect(chunks.at(-2)).toEqual({
      type: "message-metadata",
      messageMetadata: {
        state: "failed",
        errorDetail: strings.connectionLost,
        httpStatus: null,
      },
    });
    expect(chunks.at(-1)).toEqual({
      type: "error",
      errorText: strings.connectionLost,
    });
  });
});
