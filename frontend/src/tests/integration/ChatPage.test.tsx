import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { SESSION_STORAGE_KEY } from "@/hooks/useSession";
import { strings } from "@/lib/strings";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

function eventChunk(event: string, data: unknown) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function streamResponse(
  chunks: Array<{
    delay?: number;
    value: string;
  }>,
  status = 200,
) {
  const encoder = new TextEncoder();

  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        let elapsed = 0;

        for (const [index, chunk] of chunks.entries()) {
          elapsed += chunk.delay ?? 0;

          setTimeout(() => {
            controller.enqueue(encoder.encode(chunk.value));

            if (index === chunks.length - 1) {
              controller.close();
            }
          }, elapsed);
        }
      },
    }),
    {
      status,
      headers: {
        "Content-Type": "text/event-stream",
      },
    },
  );
}

function activeSessionResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: "session-1",
    snapshot_id: "snapshot-1",
    status: "active",
    channel: "web",
    message_count: 0,
    created_at: "2026-03-25T12:00:00Z",
    ...overrides,
  };
}

function twinProfileResponse(overrides: Record<string, unknown> = {}) {
  return {
    name: "ProxyMind",
    has_avatar: false,
    ...overrides,
  };
}

function stubLocalStorage() {
  const storage = new Map<string, string>();

  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => {
      storage.set(key, value);
    },
    removeItem: (key: string) => {
      storage.delete(key);
    },
    clear: () => {
      storage.clear();
    },
  });
}

function getRequestUrl(input: RequestInfo | URL) {
  if (typeof input === "string") {
    return input;
  }

  if (input instanceof URL) {
    return input.toString();
  }

  return input.url;
}

describe("ChatPage integration", () => {
  beforeEach(() => {
    stubLocalStorage();
    localStorage.clear();
    window.history.replaceState({}, "", "/");

    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders the full chat flow through the root route", async () => {
    const user = userEvent.setup();

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse(
          twinProfileResponse({
            name: "Marcus Aurelius",
          }),
        );
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
        return jsonResponse(activeSessionResponse(), 201);
      }

      if (url === "/api/chat/messages" && init?.method === "POST") {
        return streamResponse([
          {
            value: eventChunk("meta", {
              message_id: "assistant-1",
              session_id: "session-1",
              snapshot_id: "snapshot-1",
            }),
          },
          {
            delay: 60,
            value: eventChunk("token", {
              content: "Hel",
            }),
          },
          {
            delay: 700,
            value: eventChunk("token", {
              content: "lo there",
            }),
          },
          {
            delay: 100,
            value: eventChunk("done", {
              token_count_prompt: 12,
              token_count_completion: 4,
              model_name: "gemini-test",
              retrieved_chunks_count: 2,
            }),
          },
        ]);
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Marcus Aurelius" }),
    ).toBeInTheDocument();

    const input = await screen.findByLabelText(strings.inputPlaceholder);
    await user.type(input, "Hi there");
    fireEvent.keyDown(input, {
      code: "Enter",
      key: "Enter",
    });

    expect(
      await screen.findByLabelText(strings.streamingLabel),
    ).toBeInTheDocument();
    expect(await screen.findByText("Hi there")).toBeInTheDocument();
    expect(await screen.findByText("Hello there")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByLabelText(strings.streamingLabel)).toBeNull();
    });

    const messageRequest = fetchMock.mock.calls.find(
      ([input]) => getRequestUrl(input) === "/api/chat/messages",
    );

    expect(messageRequest).toBeDefined();
    expect(messageRequest?.[1]?.method).toBe("POST");
    expect(messageRequest?.[1]?.headers).toEqual({
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(messageRequest?.[1]?.body))).toEqual({
      session_id: "session-1",
      text: "Hi there",
      idempotency_key: expect.any(String),
    });
  });

  it("shows the loading skeleton while the initial session is being created", async () => {
    let resolveSession:
      | ((value: Response | PromiseLike<Response>) => void)
      | undefined;

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse(twinProfileResponse());
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolveSession = resolve;
        });
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(document.querySelector(".chat-page__loading")).toBeInTheDocument();

    resolveSession?.(jsonResponse(activeSessionResponse(), 201));

    expect(
      await screen.findByLabelText(strings.inputPlaceholder),
    ).toBeInTheDocument();
  });

  it("falls back to the default twin name when the profile API is unavailable", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse({ detail: "Profile unavailable" }, 503);
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
        return jsonResponse(activeSessionResponse(), 201);
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "ProxyMind" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByLabelText(strings.inputPlaceholder),
    ).toBeInTheDocument();
  });

  it("restores history from the persisted session", async () => {
    localStorage.setItem(SESSION_STORAGE_KEY, "session-restored");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse(twinProfileResponse());
      }

      if (
        url === "/api/chat/sessions/session-restored" &&
        init?.method === "GET"
      ) {
        return jsonResponse(
          activeSessionResponse({
            id: "session-restored",
            message_count: 4,
            messages: [
              {
                id: "message-1",
                role: "user",
                content: "First question",
                status: "received",
                citations: null,
                model_name: null,
                created_at: "2026-03-25T12:00:01Z",
              },
              {
                id: "message-2",
                role: "assistant",
                content: "First answer",
                status: "complete",
                citations: null,
                model_name: "gemini-test",
                created_at: "2026-03-25T12:00:02Z",
              },
              {
                id: "message-3",
                role: "user",
                content: "Second question",
                status: "received",
                citations: null,
                model_name: null,
                created_at: "2026-03-25T12:00:03Z",
              },
              {
                id: "message-4",
                role: "assistant",
                content: "Second answer",
                status: "complete",
                citations: null,
                model_name: "gemini-test",
                created_at: "2026-03-25T12:00:04Z",
              },
            ],
          }),
        );
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    const firstQuestion = await screen.findByText("First question");
    const firstAnswer = await screen.findByText("First answer");
    const secondQuestion = await screen.findByText("Second question");
    const secondAnswer = await screen.findByText("Second answer");

    expect(
      firstQuestion.compareDocumentPosition(firstAnswer) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      firstAnswer.compareDocumentPosition(secondQuestion) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      secondQuestion.compareDocumentPosition(secondAnswer) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByLabelText(strings.inputPlaceholder)).toBeEnabled();
  });

  it("shows the knowledge-not-ready error and retry button for HTTP 422", async () => {
    const user = userEvent.setup();

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse(twinProfileResponse());
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
        return jsonResponse(activeSessionResponse(), 201);
      }

      if (url === "/api/chat/messages" && init?.method === "POST") {
        return jsonResponse({ detail: "No active snapshot" }, 422);
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    const input = await screen.findByLabelText(strings.inputPlaceholder);
    await user.type(input, "Try now{Enter}");

    expect(
      await screen.findByText(strings.knowledgeNotReady),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: strings.retry }),
    ).toBeInTheDocument();
  });

  it("shows the already-processing error for HTTP 409", async () => {
    const user = userEvent.setup();

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse(twinProfileResponse());
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
        return jsonResponse(activeSessionResponse(), 201);
      }

      if (url === "/api/chat/messages" && init?.method === "POST") {
        return jsonResponse({ detail: "Concurrent stream active" }, 409);
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    const input = await screen.findByLabelText(strings.inputPlaceholder);
    await user.type(input, "One more{Enter}");

    expect(
      await screen.findByText(strings.alreadyProcessing),
    ).toBeInTheDocument();
  });

  it("preserves partial content and shows connection lost when the stream drops", async () => {
    const user = userEvent.setup();
    let messageAttempts = 0;

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse(twinProfileResponse());
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
        return jsonResponse(activeSessionResponse(), 201);
      }

      if (url === "/api/chat/messages" && init?.method === "POST") {
        messageAttempts += 1;

        if (messageAttempts === 1) {
          return streamResponse([
            {
              value: eventChunk("meta", {
                message_id: "assistant-1",
                session_id: "session-1",
                snapshot_id: "snapshot-1",
              }),
            },
            {
              delay: 20,
              value: eventChunk("token", {
                content: "Partial answer",
              }),
            },
          ]);
        }

        throw new TypeError("Network error");
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    const input = await screen.findByLabelText(strings.inputPlaceholder);
    await user.type(input, "Keep going{Enter}");

    expect(await screen.findByText("Partial answer")).toBeInTheDocument();
    expect(await screen.findByText(strings.connectionLost)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: strings.retry }),
    ).toBeInTheDocument();

    await waitFor(() => {
      const messageRequests = fetchMock.mock.calls.filter(
        ([input]) => getRequestUrl(input) === "/api/chat/messages",
      );

      expect(messageRequests).toHaveLength(2);
    });
  });

  it("shows a recoverable error state when session restore fails", async () => {
    const user = userEvent.setup();

    localStorage.setItem(SESSION_STORAGE_KEY, "session-broken");

    fetchMock.mockImplementation(async (input, init) => {
      const url = getRequestUrl(input);

      if (url === "/api/chat/twin" && init?.method === "GET") {
        return jsonResponse(twinProfileResponse());
      }

      if (
        url === "/api/chat/sessions/session-broken" &&
        init?.method === "GET"
      ) {
        return jsonResponse({ detail: "Backend unavailable" }, 503);
      }

      if (url === "/api/chat/sessions" && init?.method === "POST") {
        return jsonResponse(
          activeSessionResponse({ id: "session-recovered" }),
          201,
        );
      }

      throw new Error(`Unhandled request: ${url}`);
    });

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: strings.sessionUnavailable }),
    ).toBeInTheDocument();
    expect(screen.getByText("Backend unavailable")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: strings.tryAgain }));

    expect(
      await screen.findByLabelText(strings.inputPlaceholder),
    ).toBeInTheDocument();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBe("session-recovered");
  });
});
