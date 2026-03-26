import type { ChatMessageMetadata } from "@/types/chat";

const relativeTimeStrings = {
  justNow: "just now",
  minutesAgo: (value: number) => `${value}m ago`,
  hoursAgo: (value: number) => `${value}h ago`,
  daysAgo: (value: number) => `${value}d ago`,
} as const;

export const strings = {
  appTitle: "ProxyMind",
  sessionUnavailable: "Chat is temporarily unavailable.",
  emptyStateTitle: "Start the first exchange.",
  emptyStateBody:
    "Messages will appear here and new answers will stream in live.",
  conversationLabel: "Conversation timeline",
  inputPlaceholder: "Ask ProxyMind something...",
  send: "Send",
  retry: "Retry",
  tryAgain: "Try again",
  headerStatus: "Live chat",
  incomplete: "Incomplete response",
  failed: "Response failed",
  connectionLost: "Connection lost",
  knowledgeNotReady: "Knowledge is not ready yet.",
  alreadyProcessing: "Another response is already in progress.",
  emptyMessage: "Message text is empty.",
  emptyResponseBody: "The response body is empty.",
  scrollToBottom: "Jump to latest",
  streamingLabel: "Streaming response",
  sourcesCount: (value: number) => `Sources (${value})`,
  imageLightboxClose: "Close image preview",
  imageLightboxTitle: "Image preview",
  imageLightboxDescription: "Full-size preview for an image citation.",
  imageLightboxImageAlt: "Expanded citation image",
  profileTitle: "Edit profile",
  profileDescription: "Update the twin name and avatar shown in chat.",
  profileNameLabel: "Twin name",
  profileSave: "Save",
  profileRemoveAvatar: "Remove avatar",
  profileChangeAvatar: "Change avatar",
  profileSettings: "Open profile settings",
  profileClose: "Close profile editor",
  profileAvatarAlt: "Twin avatar preview",
  profileSaveFailed: "Failed to save the profile.",
  profileUploadFailed: "Failed to upload the avatar.",
  profileRemoveFailed: "Failed to remove the avatar.",
  requestFailed: (status: number) => `Request failed with status ${status}`,
  relativeTime: relativeTimeStrings,
} as const;

export function formatRelativeTime(
  value: Date | string,
  now: Date = new Date(),
) {
  const target = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(target.getTime())) {
    return "";
  }

  const diffMs = Math.max(0, now.getTime() - target.getTime());
  const diffMinutes = Math.floor(diffMs / 60_000);

  if (diffMinutes < 1) {
    return strings.relativeTime.justNow;
  }

  if (diffMinutes < 60) {
    return strings.relativeTime.minutesAgo(diffMinutes);
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return strings.relativeTime.hoursAgo(diffHours);
  }

  return strings.relativeTime.daysAgo(Math.floor(diffHours / 24));
}

export function formatMessageError(
  metadata: Pick<ChatMessageMetadata, "errorDetail" | "httpStatus"> | undefined,
) {
  if (metadata?.httpStatus === 422) {
    return strings.knowledgeNotReady;
  }

  if (metadata?.httpStatus === 409) {
    return strings.alreadyProcessing;
  }

  if (metadata?.errorDetail === strings.connectionLost) {
    return strings.connectionLost;
  }

  return metadata?.errorDetail ?? strings.failed;
}
