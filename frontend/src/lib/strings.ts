import type { ChatMessageMetadata } from "@/types/chat";

const relativeTimeStrings = {
  justNow: "just now",
  minutesAgo: (value: number) => `${value}m ago`,
  hoursAgo: (value: number) => `${value}h ago`,
  daysAgo: (value: number) => `${value}d ago`,
} as const;

export const strings = {
  appTitle: "ProxyMind",
  authEyebrow: "Private access",
  authLoading: "Restoring your session",
  authLoadingDescription:
    "Checking your refresh cookie and preparing a secure chat session.",
  authRequestFailed: "Authentication request failed.",
  authenticationRequired: "Your session has expired. Please sign in again.",
  signInTitle: "Return to your private twin workspace.",
  signInDescription:
    "ProxyMind keeps chat, profile, and session history scoped to your account.",
  signInAction: "Sign in",
  signingIn: "Signing in...",
  registerTitle: "Create an account for your twin.",
  registerDescription:
    "Register once, verify your email, and every chat session becomes user-scoped.",
  registerAction: "Create account",
  registering: "Creating account...",
  forgotPasswordTitle: "Recover access without losing history.",
  forgotPasswordDescription:
    "Request a password reset link and continue from a fresh authenticated session.",
  forgotPasswordAction: "Forgot your password?",
  resetPasswordTitle: "Set a new password.",
  resetPasswordDescription:
    "Use the secure reset token from your email to finish account recovery.",
  resetPasswordAction: "Reset password",
  resettingPassword: "Resetting password...",
  verifyEmailTitle: "Verify your email.",
  verifyEmailDescription:
    "Email verification activates the account and unlocks the protected chat surface.",
  verifyingEmail: "Verifying your email...",
  invalidVerificationLink: "This verification link is missing or invalid.",
  emailLabel: "Email",
  passwordLabel: "Password",
  passwordPlaceholder: "At least 8 characters",
  confirmPasswordLabel: "Confirm password",
  passwordConfirmationMismatch: "Passwords do not match.",
  newPasswordLabel: "New password",
  displayNameLabel: "Display name",
  displayNamePlaceholder: "How should ProxyMind address you?",
  sendResetLink: "Send reset link",
  sendingResetLink: "Sending link...",
  resetTokenLabel: "Reset token",
  backToSignIn: "Back to sign in",
  noAccountYet: "Need access?",
  alreadyHaveAccount: "Already verified?",
  adminSignInTitle: "Unlock the control surface.",
  adminSignInDescription:
    "Admin mode stays separate from end-user auth and still uses the configured API key.",
  adminEyebrow: "ProxyMind Admin",
  adminKeyLabel: "Admin API key",
  adminKeyPlaceholder: "Enter admin API key...",
  adminKeyRequired: "API key is required.",
  signOutAction: "Sign out",
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
