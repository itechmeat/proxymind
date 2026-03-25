import type {
  CitationsEvent,
  DoneEvent,
  ErrorEvent,
  MetaEvent,
  SSEEvent,
  TokenEvent,
} from "@/types/chat";

function parseEvent(eventType: string, rawData: string): SSEEvent | null {
  let payload: unknown;

  try {
    payload = JSON.parse(rawData);
  } catch {
    return null;
  }

  if (!payload || typeof payload !== "object") {
    return null;
  }

  switch (eventType) {
    case "meta":
      return {
        type: "meta",
        ...(payload as Omit<MetaEvent, "type">),
      };
    case "token":
      return {
        type: "token",
        ...(payload as Omit<TokenEvent, "type">),
      };
    case "citations":
      return {
        type: "citations",
        ...(payload as Omit<CitationsEvent, "type">),
      };
    case "done":
      return {
        type: "done",
        ...(payload as Omit<DoneEvent, "type">),
      };
    case "error":
      return {
        type: "error",
        ...(payload as Omit<ErrorEvent, "type">),
      };
    default:
      return null;
  }
}

function extractEvent(block: string): SSEEvent | null {
  const lines = block.split("\n");
  let eventType = "";
  const dataLines: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (!line || line.startsWith(":")) {
      continue;
    }

    if (line.startsWith("event:")) {
      eventType = line.slice("event:".length).trim();
      continue;
    }

    if (line.startsWith("data:")) {
      const data = line.slice("data:".length);
      dataLines.push(data.startsWith(" ") ? data.slice(1) : data);
    }
  }

  if (!eventType || dataLines.length === 0) {
    return null;
  }

  return parseEvent(eventType, dataLines.join("\n"));
}

export async function* parseSSEStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SSEEvent> {
  const textDecoder = new TextDecoder();
  const reader = stream.getReader();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      buffer += textDecoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");

      while (true) {
        const boundaryIndex = buffer.indexOf("\n\n");
        if (boundaryIndex === -1) {
          break;
        }

        const block = buffer.slice(0, boundaryIndex);
        buffer = buffer.slice(boundaryIndex + 2);

        const event = extractEvent(block);
        if (event) {
          yield event;
        }
      }
    }

    buffer += textDecoder.decode();
    buffer = buffer.replace(/\r\n/g, "\n");
    const trailingEvent = extractEvent(buffer);
    if (trailingEvent) {
      yield trailingEvent;
    }
  } finally {
    reader.releaseLock();
  }
}
