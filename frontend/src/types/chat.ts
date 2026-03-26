import type { UIMessage } from "ai";

export type SessionStatus = "active" | "closed";

export type SessionChannel =
  | "web"
  | "api"
  | "telegram"
  | "facebook"
  | "vk"
  | "instagram"
  | "tiktok";

export type MessageRole = "user" | "assistant";

export type MessageStatus =
  | "received"
  | "streaming"
  | "complete"
  | "partial"
  | "failed";

export interface AnchorResponse {
  page: number | null;
  chapter: string | null;
  section: string | null;
  timecode: string | null;
}

export interface CitationResponse {
  index: number;
  source_id: string;
  source_title: string;
  source_type: string;
  url: string | null;
  anchor: AnchorResponse;
  text_citation: string;
}

export interface TwinProfile {
  name: string;
  has_avatar: boolean;
}

export interface AvatarUploadResponse {
  has_avatar: boolean;
}

export interface SessionResponse {
  id: string;
  snapshot_id: string | null;
  status: SessionStatus;
  channel: SessionChannel;
  message_count: number;
  created_at: string;
}

export interface SendMessageRequest {
  session_id: string;
  text: string;
  idempotency_key?: string | null;
}

export interface MessageInHistory {
  id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  citations: CitationResponse[] | null;
  model_name: string | null;
  created_at: string;
}

export interface SessionWithMessagesResponse extends SessionResponse {
  messages: MessageInHistory[];
}

export interface MetaEvent {
  type: "meta";
  message_id: string;
  session_id: string;
  snapshot_id: string | null;
}

export interface TokenEvent {
  type: "token";
  content: string;
}

export interface CitationsEvent {
  type: "citations";
  citations: CitationResponse[];
}

export interface DoneEvent {
  type: "done";
  token_count_prompt: number | null;
  token_count_completion: number | null;
  model_name: string | null;
  retrieved_chunks_count: number | null;
}

export interface ErrorEvent {
  type: "error";
  detail: string;
}

export type SSEEvent =
  | MetaEvent
  | TokenEvent
  | CitationsEvent
  | DoneEvent
  | ErrorEvent;

export type ChatMessageState = "complete" | "streaming" | "partial" | "failed";

export interface ChatMessageMetadata {
  sessionId?: string | null;
  snapshotId?: string | null;
  citations?: CitationResponse[] | null;
  modelName?: string | null;
  retrievedChunksCount?: number | null;
  tokenCountPrompt?: number | null;
  tokenCountCompletion?: number | null;
  createdAt?: string;
  state?: ChatMessageState;
  errorDetail?: string | null;
  httpStatus?: number | null;
}

export type ChatMessage = UIMessage<ChatMessageMetadata>;
