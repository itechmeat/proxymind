import type { ChatTransport } from "ai";

import { buildApiUrl } from "@/lib/api";
import { parseSSEStream } from "@/lib/sse-parser";
import { strings } from "@/lib/strings";
import type {
  ChatMessage,
  ChatMessageMetadata,
  CitationResponse,
  SSEEvent,
} from "@/types/chat";

type TransportChunk =
  | {
      type: "start";
      messageId?: string;
      messageMetadata?: ChatMessageMetadata;
    }
  | {
      type: "text-start";
      id: string;
    }
  | {
      type: "text-delta";
      id: string;
      delta: string;
    }
  | {
      type: "text-end";
      id: string;
    }
  | {
      type: "finish";
      finishReason?: "stop" | "error";
      messageMetadata?: ChatMessageMetadata;
    }
  | {
      type: "message-metadata";
      messageMetadata: ChatMessageMetadata;
    }
  | {
      type: "error";
      errorText: string;
    };

export interface ProxyMindTransportOptions {
  sessionId: string;
  api?: string;
  fetch?: typeof fetch;
  generateId?: () => string;
  getAccessToken: (options?: {
    forceRefresh?: boolean;
  }) => Promise<string | null>;
  onAuthFailure?: () => void;
  onCitations?: (payload: {
    messageId: string;
    citations: CitationResponse[];
  }) => void;
  onSessionInvalidated?: () => void;
}

function getMessageText(message: ChatMessage | undefined) {
  if (!message) {
    return "";
  }

  return message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("")
    .trim();
}

async function readErrorDetail(response: Response) {
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) {
      return body.detail;
    }
  } catch {
    // Ignore invalid JSON and fall back to status text.
  }

  return response.statusText || strings.requestFailed(response.status);
}

function shouldInvalidateSession(status: number, detail: string) {
  if (status === 404) {
    return true;
  }

  return status === 403 && detail === "Session belongs to a different user";
}

function createChunkStream(chunks: TransportChunk[]) {
  return new ReadableStream<TransportChunk>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

function getHttpErrorMetadata(
  detail: string,
  status: number,
): ChatMessageMetadata {
  return {
    state: "failed",
    errorDetail: detail,
    httpStatus: status,
  };
}

function getConnectionLostMetadata(): ChatMessageMetadata {
  return {
    state: "failed",
    errorDetail: strings.connectionLost,
    httpStatus: null,
  };
}

function createErrorStream(
  messageId: string,
  metadata: ChatMessageMetadata,
  detail: string,
) {
  return createChunkStream([
    {
      type: "start",
      messageId,
      messageMetadata: metadata,
    },
    {
      type: "error",
      errorText: detail,
    },
  ]);
}

function createSyntheticHttpErrorStream(
  messageId: string,
  detail: string,
  status: number,
) {
  return createErrorStream(
    messageId,
    getHttpErrorMetadata(detail, status),
    detail,
  );
}

/**
 * AI SDK transport spike findings for S5-01 (verified against local AI SDK 6.0.138 source/docs):
 * - Chosen integration point: `useChat({ transport })` with a custom `ChatTransport`, not a `fetch` override.
 * - Initial history parameter name: `messages` on `ChatInit`, not `initialMessages`.
 * - `useChat` status enum values: `submitted`, `streaming`, `ready`, `error`.
 * - Resulting approach: A. UI state uses `UIMessage.parts`, and backend SSE is mapped into AI SDK UI chunks here.
 */
export class ProxyMindTransport implements ChatTransport<ChatMessage> {
  private readonly api: string;
  private readonly fetchImpl: typeof fetch;
  private readonly generateId: () => string;
  private readonly getAccessToken: ProxyMindTransportOptions["getAccessToken"];
  private readonly onAuthFailure?: ProxyMindTransportOptions["onAuthFailure"];
  private readonly onCitations?: ProxyMindTransportOptions["onCitations"];
  private readonly onSessionInvalidated?: ProxyMindTransportOptions["onSessionInvalidated"];
  private readonly sessionId: string;

  constructor({
    sessionId,
    api = "/api/chat/messages",
    fetch: fetchImpl = globalThis.fetch.bind(globalThis),
    generateId = () => crypto.randomUUID(),
    getAccessToken,
    onAuthFailure,
    onCitations,
    onSessionInvalidated,
  }: ProxyMindTransportOptions) {
    this.sessionId = sessionId;
    this.api = api;
    this.fetchImpl = fetchImpl;
    this.generateId = generateId;
    this.getAccessToken = getAccessToken;
    this.onAuthFailure = onAuthFailure;
    this.onCitations = onCitations;
    this.onSessionInvalidated = onSessionInvalidated;
  }

  sendMessages: ChatTransport<ChatMessage>["sendMessages"] = async ({
    messages,
    abortSignal,
  }) => {
    const text = getMessageText(messages[messages.length - 1]);
    const localMessageId = this.generateId();

    if (!text) {
      // AI SDK transport typing is broader than the concrete UI chunk stream emitted here.
      return createSyntheticHttpErrorStream(
        localMessageId,
        strings.emptyMessage,
        400,
      ) as never;
    }

    const idempotencyKey = this.generateId();
    const textPartId = this.generateId();

    let started = false;
    let assistantMessageId: string | null = null;
    let textStarted = false;
    let textEnded = false;
    let accumulatedText = "";

    const emitStart = (
      controller: ReadableStreamDefaultController<TransportChunk>,
      metadata?: ChatMessageMetadata,
      messageId?: string,
    ) => {
      if (started) {
        if (metadata) {
          controller.enqueue({
            type: "message-metadata",
            messageMetadata: metadata,
          });
        }
        return;
      }

      assistantMessageId = messageId ?? assistantMessageId ?? localMessageId;
      controller.enqueue({
        type: "start",
        messageId: assistantMessageId,
        ...(metadata ? { messageMetadata: metadata } : {}),
      });
      started = true;
    };

    const emitTextStart = (
      controller: ReadableStreamDefaultController<TransportChunk>,
    ) => {
      if (textStarted) {
        return;
      }

      if (!started) {
        emitStart(controller, {
          sessionId: this.sessionId,
          state: "streaming",
        });
      }
      controller.enqueue({
        type: "text-start",
        id: textPartId,
      });
      textStarted = true;
    };

    const emitTextEnd = (
      controller: ReadableStreamDefaultController<TransportChunk>,
    ) => {
      if (!textStarted || textEnded) {
        return;
      }

      controller.enqueue({
        type: "text-end",
        id: textPartId,
      });
      textEnded = true;
    };

    const emitFailure = (
      controller: ReadableStreamDefaultController<TransportChunk>,
      detail: string,
      metadata: ChatMessageMetadata,
    ) => {
      const wasStarted = started;
      if (!wasStarted) {
        emitStart(controller, metadata);
      } else {
        emitTextEnd(controller);
        controller.enqueue({
          type: "message-metadata",
          messageMetadata: metadata,
        });
      }
      controller.enqueue({
        type: "error",
        errorText: detail,
      });
      controller.close();
    };

    const processEvent = (
      controller: ReadableStreamDefaultController<TransportChunk>,
      event: SSEEvent,
      replayState: { baseline: string; buffer: string } | null,
    ): "continue" | "done" | "error" => {
      switch (event.type) {
        case "meta": {
          assistantMessageId = event.message_id;
          emitStart(
            controller,
            {
              sessionId: event.session_id,
              snapshotId: event.snapshot_id,
              state: "streaming",
            },
            event.message_id,
          );
          return "continue";
        }

        case "token": {
          emitTextStart(controller);

          let delta = event.content;
          if (replayState != null) {
            replayState.buffer += event.content;
            delta = replayState.buffer.slice(replayState.baseline.length);
          }

          if (delta) {
            accumulatedText += delta;
            controller.enqueue({
              type: "text-delta",
              id: textPartId,
              delta,
            });
          }

          return "continue";
        }

        case "citations": {
          if (assistantMessageId != null) {
            this.onCitations?.({
              messageId: assistantMessageId,
              citations: event.citations,
            });
          }

          emitStart(controller, {
            citations: event.citations,
          });
          return "continue";
        }

        case "done": {
          emitTextEnd(controller);
          controller.enqueue({
            type: "finish",
            finishReason: "stop",
            messageMetadata: {
              modelName: event.model_name,
              retrievedChunksCount: event.retrieved_chunks_count,
              tokenCountPrompt: event.token_count_prompt,
              tokenCountCompletion: event.token_count_completion,
              state: "complete",
            },
          });
          controller.close();
          return "done";
        }

        case "error": {
          emitFailure(controller, event.detail, {
            state: "failed",
            errorDetail: event.detail,
          });
          return "error";
        }
      }
    };

    const emitAuthFailure = (
      controller: ReadableStreamDefaultController<TransportChunk>,
      detail: string = strings.authenticationRequired,
    ) => {
      this.onAuthFailure?.();
      emitFailure(controller, detail, getHttpErrorMetadata(detail, 401));
    };

    const attemptStream = async ({
      accessToken,
      allowUnauthorizedRetry,
      controller,
      replayBaseline,
      emitImmediateFailures,
    }: {
      accessToken: string | null;
      allowUnauthorizedRetry: boolean;
      controller: ReadableStreamDefaultController<TransportChunk>;
      replayBaseline: string | null;
      emitImmediateFailures: boolean;
    }): Promise<"done" | "error" | "closed"> => {
      let response: Response;
      const replayState =
        replayBaseline == null
          ? null
          : {
              baseline: replayBaseline,
              buffer: "",
            };

      if (!accessToken) {
        if (emitImmediateFailures) {
          emitAuthFailure(controller);
          return "error";
        }
        return "closed";
      }

      try {
        response = await this.fetchImpl(buildApiUrl(this.api), {
          method: "POST",
          headers: {
            Authorization: `Bearer ${accessToken}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            session_id: this.sessionId,
            text,
            idempotency_key: idempotencyKey,
          }),
          signal: abortSignal,
        });
      } catch {
        if (emitImmediateFailures) {
          emitFailure(
            controller,
            strings.connectionLost,
            getConnectionLostMetadata(),
          );
          return "error";
        }
        return "closed";
      }

      if (response.status === 401 && allowUnauthorizedRetry) {
        const refreshedAccessToken = await this.getAccessToken({
          forceRefresh: true,
        });

        if (!refreshedAccessToken) {
          if (emitImmediateFailures) {
            emitAuthFailure(controller);
            return "error";
          }

          return "closed";
        }

        return await attemptStream({
          accessToken: refreshedAccessToken,
          allowUnauthorizedRetry: false,
          controller,
          replayBaseline,
          emitImmediateFailures,
        });
      }

      if (!response.ok) {
        if (response.status === 401) {
          if (emitImmediateFailures) {
            emitAuthFailure(controller, await readErrorDetail(response));
            return "error";
          }

          return "closed";
        }

        const detail = await readErrorDetail(response);
        if (shouldInvalidateSession(response.status, detail)) {
          this.onSessionInvalidated?.();
        }

        if (!emitImmediateFailures) {
          return "closed";
        }

        emitFailure(
          controller,
          detail,
          getHttpErrorMetadata(detail, response.status),
        );
        return "error";
      }

      if (!response.body) {
        if (!emitImmediateFailures) {
          return "closed";
        }

        emitFailure(controller, strings.emptyResponseBody, {
          state: "failed",
          errorDetail: strings.emptyResponseBody,
        });
        return "error";
      }

      for await (const event of parseSSEStream(response.body)) {
        const result = processEvent(controller, event, replayState);
        if (result !== "continue") {
          return result;
        }
      }

      return "closed";
    };

    return new ReadableStream<TransportChunk>({
      start: async (controller) => {
        try {
          const accessToken = await this.getAccessToken();
          const firstAttempt = await attemptStream({
            accessToken,
            allowUnauthorizedRetry: true,
            controller,
            replayBaseline: null,
            emitImmediateFailures: true,
          });

          if (firstAttempt !== "closed") {
            return;
          }

          const retryAttempt = await attemptStream({
            accessToken: await this.getAccessToken(),
            allowUnauthorizedRetry: true,
            controller,
            replayBaseline: accumulatedText,
            emitImmediateFailures: false,
          });

          if (retryAttempt !== "done") {
            emitFailure(
              controller,
              strings.connectionLost,
              getConnectionLostMetadata(),
            );
          }
        } catch {
          emitFailure(
            controller,
            strings.connectionLost,
            getConnectionLostMetadata(),
          );
        }
      },
    }) as never;
  };

  reconnectToStream: ChatTransport<ChatMessage>["reconnectToStream"] =
    async () => null;
}
