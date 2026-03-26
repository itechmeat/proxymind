import { describe, expect, it } from "vitest";

import { parseSSEStream } from "@/lib/sse-parser";

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

async function collectEvents(chunks: string[]) {
  const stream = streamFromChunks(chunks);
  const events = [];

  for await (const event of parseSSEStream(stream)) {
    events.push(event);
  }

  return events;
}

describe("parseSSEStream", () => {
  it("parses a single event", async () => {
    const events = await collectEvents([
      'event: token\ndata: {"content":"hello"}\n\n',
    ]);

    expect(events).toEqual([{ type: "token", content: "hello" }]);
  });

  it("parses multiple events", async () => {
    const events = await collectEvents([
      'event: meta\ndata: {"message_id":"m1","session_id":"s1","snapshot_id":"snap"}\n\n',
      'event: done\ndata: {"token_count_prompt":1,"token_count_completion":2,"model_name":"test-model","retrieved_chunks_count":3}\n\n',
    ]);

    expect(events).toEqual([
      {
        type: "meta",
        message_id: "m1",
        session_id: "s1",
        snapshot_id: "snap",
      },
      {
        type: "done",
        token_count_prompt: 1,
        token_count_completion: 2,
        model_name: "test-model",
        retrieved_chunks_count: 3,
      },
    ]);
  });

  it("parses events with CRLF delimiters", async () => {
    const events = await collectEvents([
      'event: token\r\ndata: {"content":"hello"}\r\n\r\n',
    ]);

    expect(events).toEqual([{ type: "token", content: "hello" }]);
  });

  it("skips heartbeat comments", async () => {
    const events = await collectEvents([
      ": heartbeat\n\n",
      'event: token\ndata: {"content":"hello"}\n\n',
    ]);

    expect(events).toEqual([{ type: "token", content: "hello" }]);
  });

  it("buffers partial chunks", async () => {
    const events = await collectEvents([
      'event: citations\ndata: {"citations":[{"index":1,"source_id":"s1",',
      '"source_title":"Doc","source_type":"pdf","url":null,"anchor":{"page":1,"chapter":null,"section":null,"timecode":null},"text_citation":"Doc, p. 1"}]}\n\n',
    ]);

    expect(events).toEqual([
      {
        type: "citations",
        citations: [
          {
            index: 1,
            source_id: "s1",
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
    ]);
  });

  it("parses error events", async () => {
    const events = await collectEvents([
      'event: error\ndata: {"detail":"LLM response timed out"}\n\n',
    ]);

    expect(events).toEqual([
      {
        type: "error",
        detail: "LLM response timed out",
      },
    ]);
  });

  it("skips malformed JSON and keeps parsing", async () => {
    const events = await collectEvents([
      'event: token\ndata: {"content":"bad"\n\n',
      'event: token\ndata: {"content":"good"}\n\n',
    ]);

    expect(events).toEqual([{ type: "token", content: "good" }]);
  });

  it("returns no events for an empty stream", async () => {
    const events = await collectEvents([]);

    expect(events).toEqual([]);
  });
});
