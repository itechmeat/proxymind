import type {
  ChatMessage,
  ChatMessageMetadata,
  ChatMessageState,
  MessageInHistory,
  MessageStatus,
} from "@/types/chat";

function mapMessageState(status: MessageStatus): ChatMessageState {
  if (status === "received") {
    return "complete";
  }

  if (status === "streaming") {
    return "partial";
  }

  return status;
}

function buildMetadata(message: MessageInHistory): ChatMessageMetadata {
  return {
    citations: message.citations,
    modelName: message.model_name,
    createdAt: message.created_at,
    state: mapMessageState(message.status),
  };
}

export function toUIMessages(messages: MessageInHistory[]): ChatMessage[] {
  return messages.map((message) => {
    return {
      id: message.id,
      role: message.role,
      metadata: buildMetadata(message),
      parts:
        message.content.length > 0
          ? [
              {
                type: "text",
                text: message.content,
                ...(message.role === "assistant" ? { state: "done" } : {}),
              },
            ]
          : [],
    };
  });
}

export function getMessageText(message: ChatMessage) {
  return message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
}
