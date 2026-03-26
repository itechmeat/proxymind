import { useChat } from "@ai-sdk/react";
import { type ReactNode, useEffect, useState } from "react";

import { ChatHeader } from "@/components/ChatHeader";
import { ChatInput } from "@/components/ChatInput";
import { MessageList } from "@/components/MessageList";
import { ProfileEditModal } from "@/components/ProfileEditModal";
import { Button } from "@/components/ui/button";
import { useSession } from "@/hooks/useSession";
import {
  buildApiUrl,
  deleteTwinAvatar,
  getTwinProfile,
  updateTwinProfile,
  uploadTwinAvatar,
} from "@/lib/api";
import { appConfig } from "@/lib/config";
import { getMessageText } from "@/lib/message-adapter";
import { strings } from "@/lib/strings";
import { ProxyMindTransport } from "@/lib/transport";
import type { ChatMessage, TwinProfile } from "@/types/chat";

import "./ChatPage.css";

interface DisplayTwinProfile {
  avatarUrl?: string;
  hasAvatar: boolean;
  name: string;
}

interface ChatPageFrameProps {
  body: ReactNode;
  footer?: ReactNode;
  onOpenProfileSettings?: () => void;
  profile: DisplayTwinProfile;
}

function resolveFallbackProfile(): DisplayTwinProfile {
  const name = appConfig.twinName || strings.appTitle;
  const avatarUrl = appConfig.twinAvatarUrl || undefined;

  return {
    avatarUrl,
    hasAvatar: Boolean(avatarUrl),
    name,
  };
}

function resolveApiProfile(
  profile: TwinProfile | null,
): DisplayTwinProfile | null {
  if (!profile?.name?.trim()) {
    return null;
  }

  return {
    avatarUrl: profile.has_avatar
      ? buildApiUrl("/api/chat/twin/avatar")
      : undefined,
    hasAvatar: profile.has_avatar,
    name: profile.name.trim(),
  };
}

function ChatPageFrame({
  body,
  footer,
  onOpenProfileSettings,
  profile,
}: ChatPageFrameProps) {
  return (
    <main className="chat-page">
      <div
        aria-hidden="true"
        className="chat-page__glow chat-page__glow--warm"
      />
      <div
        aria-hidden="true"
        className="chat-page__glow chat-page__glow--cool"
      />

      <div className="chat-page__shell">
        <ChatHeader
          adminMode={appConfig.adminMode}
          avatarUrl={profile.avatarUrl}
          name={profile.name}
          onOpenSettings={onOpenProfileSettings}
        />
        <div className="chat-page__body">{body}</div>
        {footer}
      </div>
    </main>
  );
}

function ChatPageLoading({
  onOpenProfileSettings,
  profile,
}: Pick<ChatPageFrameProps, "onOpenProfileSettings" | "profile">) {
  return (
    <ChatPageFrame
      body={
        <div aria-hidden="true" className="chat-page__loading">
          <div className="chat-page__loading-card chat-page__loading-card--wide" />
          <div className="chat-page__loading-card" />
          <div className="chat-page__loading-card chat-page__loading-card--narrow" />
        </div>
      }
      onOpenProfileSettings={onOpenProfileSettings}
      profile={profile}
    />
  );
}

interface ChatPageErrorProps {
  detail: string;
  onRetry: () => void;
  onOpenProfileSettings?: () => void;
  profile: DisplayTwinProfile;
}

function ChatPageError({
  detail,
  onOpenProfileSettings,
  onRetry,
  profile,
}: ChatPageErrorProps) {
  return (
    <ChatPageFrame
      body={
        <div className="chat-page__status-card">
          <h2 className="chat-page__status-title">
            {strings.sessionUnavailable}
          </h2>
          <p className="chat-page__status-detail">{detail}</p>
          <Button onClick={onRetry} type="button">
            {strings.tryAgain}
          </Button>
        </div>
      }
      onOpenProfileSettings={onOpenProfileSettings}
      profile={profile}
    />
  );
}

function findRetryTarget(
  messages: ChatMessage[],
  failedAssistantMessageId: string,
) {
  const failedIndex = messages.findIndex(
    (message) => message.id === failedAssistantMessageId,
  );

  if (failedIndex <= 0) {
    return null;
  }

  for (let index = failedIndex - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role !== "user") {
      continue;
    }

    const text = getMessageText(message).trim();
    if (!text) {
      return null;
    }

    return {
      messageId: message.id,
      text,
    };
  }

  return null;
}

interface ChatPageInnerProps {
  initialMessages: ChatMessage[];
  onOpenProfileSettings?: () => void;
  profile: DisplayTwinProfile;
  sessionId: string;
}

function ChatPageInner({
  initialMessages,
  onOpenProfileSettings,
  profile,
  sessionId,
}: ChatPageInnerProps) {
  const [transport] = useState(
    () =>
      new ProxyMindTransport({
        sessionId,
      }),
  );

  const { clearError, messages, sendMessage, status } = useChat<ChatMessage>({
    id: sessionId,
    messages: initialMessages,
    transport,
  });

  const handleSend = async (text: string) => {
    clearError();
    await sendMessage({ text });
  };

  const handleRetry = async (messageId: string) => {
    clearError();

    const retryTarget = findRetryTarget(messages, messageId);
    if (!retryTarget) {
      return;
    }

    await sendMessage({
      text: retryTarget.text,
      messageId: retryTarget.messageId,
    });
  };

  return (
    <ChatPageFrame
      body={
        <MessageList
          messages={messages}
          onRetry={(messageId) => {
            void handleRetry(messageId);
          }}
          twinAvatarUrl={profile.avatarUrl}
          twinName={profile.name}
        />
      }
      footer={<ChatInput onSend={(text) => handleSend(text)} status={status} />}
      onOpenProfileSettings={onOpenProfileSettings}
      profile={profile}
    />
  );
}

interface ChatPageLoaderProps {
  onOpenProfileSettings?: () => void;
  profile: DisplayTwinProfile;
}

function ChatPageLoader({
  onOpenProfileSettings,
  profile,
}: ChatPageLoaderProps) {
  const { createNewSession, error, initialMessages, isLoading, sessionId } =
    useSession();

  if (isLoading) {
    return (
      <ChatPageLoading
        onOpenProfileSettings={onOpenProfileSettings}
        profile={profile}
      />
    );
  }

  if (error || !sessionId) {
    return (
      <ChatPageError
        detail={error ?? strings.sessionUnavailable}
        onOpenProfileSettings={onOpenProfileSettings}
        onRetry={() => {
          void createNewSession();
        }}
        profile={profile}
      />
    );
  }

  return (
    <ChatPageInner
      initialMessages={initialMessages}
      key={sessionId}
      onOpenProfileSettings={onOpenProfileSettings}
      profile={profile}
      sessionId={sessionId}
    />
  );
}

export function ChatPage() {
  const [profile, setProfile] = useState<DisplayTwinProfile>(
    resolveFallbackProfile,
  );
  const [profileModalOpen, setProfileModalOpen] = useState(false);

  useEffect(() => {
    let active = true;

    const loadProfile = async () => {
      try {
        const apiProfile = resolveApiProfile(await getTwinProfile());
        if (active && apiProfile) {
          setProfile(apiProfile);
          return;
        }
      } catch {
        // Fall back to environment defaults when the public profile endpoint is unavailable.
      }

      if (active) {
        setProfile(resolveFallbackProfile());
      }
    };

    void loadProfile();

    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <ChatPageLoader
        onOpenProfileSettings={() => {
          setProfileModalOpen(true);
        }}
        profile={profile}
      />

      <ProfileEditModal
        avatarUrl={profile.avatarUrl}
        hasAvatar={profile.hasAvatar}
        name={profile.name}
        onOpenChange={setProfileModalOpen}
        onRemoveAvatar={async () => {
          const response = await deleteTwinAvatar();
          setProfile((currentProfile) => ({
            ...currentProfile,
            avatarUrl: undefined,
            hasAvatar: response.has_avatar,
          }));
        }}
        onSave={async (name) => {
          const nextProfile = resolveApiProfile(await updateTwinProfile(name));
          if (nextProfile) {
            setProfile(nextProfile);
          }
        }}
        onUploadAvatar={async (file) => {
          const response = await uploadTwinAvatar(file);
          setProfile((currentProfile) => ({
            ...currentProfile,
            avatarUrl: response.has_avatar
              ? buildApiUrl("/api/chat/twin/avatar")
              : undefined,
            hasAvatar: response.has_avatar,
          }));
        }}
        open={profileModalOpen}
      />
    </>
  );
}
