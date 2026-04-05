import { useChat } from "@ai-sdk/react";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { ChatHeader } from "@/components/ChatHeader";
import { ChatInput } from "@/components/ChatInput";
import { MessageList } from "@/components/MessageList";
import { ProfileEditModal } from "@/components/ProfileEditModal";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useSession } from "@/hooks/useSession";
import { useUserAuth } from "@/hooks/useUserAuth";
import {
  type BlobUrlHandle,
  deleteTwinAvatar,
  getTwinAvatarUrl,
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
  avatarRevoke?: () => void;
  avatarUrl?: string;
  hasAvatar: boolean;
  name: string;
}

interface ChatPageFrameProps {
  body: ReactNode;
  canOpenProfileSettings?: boolean;
  footer?: ReactNode;
  onOpenProfileSettings?: () => void;
  onSignOut?: () => void;
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
  profile: TwinProfile,
  avatarHandle?: BlobUrlHandle,
): DisplayTwinProfile {
  return {
    avatarRevoke: avatarHandle?.revoke,
    avatarUrl: avatarHandle?.url,
    hasAvatar: profile.has_avatar,
    name: profile.name.trim(),
  };
}

function ChatPageFrame({
  body,
  canOpenProfileSettings,
  footer,
  onOpenProfileSettings,
  onSignOut,
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
          canOpenSettings={canOpenProfileSettings}
          name={profile.name}
          onOpenSettings={onOpenProfileSettings}
          onSignOut={onSignOut}
        />
        <div className="chat-page__body">{body}</div>
        {footer}
      </div>
    </main>
  );
}

function ChatPageLoading({
  canOpenProfileSettings,
  onOpenProfileSettings,
  onSignOut,
  profile,
}: Pick<
  ChatPageFrameProps,
  "canOpenProfileSettings" | "onOpenProfileSettings" | "onSignOut" | "profile"
>) {
  return (
    <ChatPageFrame
      body={
        <div aria-hidden="true" className="chat-page__loading">
          <div className="chat-page__loading-card chat-page__loading-card--wide" />
          <div className="chat-page__loading-card" />
          <div className="chat-page__loading-card chat-page__loading-card--narrow" />
        </div>
      }
      canOpenProfileSettings={canOpenProfileSettings}
      onOpenProfileSettings={onOpenProfileSettings}
      onSignOut={onSignOut}
      profile={profile}
    />
  );
}

interface ChatPageErrorProps {
  canOpenProfileSettings?: boolean;
  detail: string;
  onRetry: () => void;
  onOpenProfileSettings?: () => void;
  onSignOut?: () => void;
  profile: DisplayTwinProfile;
}

function ChatPageError({
  canOpenProfileSettings,
  detail,
  onOpenProfileSettings,
  onRetry,
  onSignOut,
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
      canOpenProfileSettings={canOpenProfileSettings}
      onOpenProfileSettings={onOpenProfileSettings}
      onSignOut={onSignOut}
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
  canOpenProfileSettings?: boolean;
  initialMessages: ChatMessage[];
  onAuthFailure: () => void;
  onOpenProfileSettings?: () => void;
  onSignOut?: () => void;
  onSessionInvalidated: () => void;
  profile: DisplayTwinProfile;
  sessionId: string;
}

function ChatPageInner({
  canOpenProfileSettings,
  initialMessages,
  onAuthFailure,
  onOpenProfileSettings,
  onSignOut,
  onSessionInvalidated,
  profile,
  sessionId,
}: ChatPageInnerProps) {
  const { getAccessToken } = useUserAuth();
  const [transport] = useState(
    () =>
      new ProxyMindTransport({
        getAccessToken,
        onAuthFailure,
        onSessionInvalidated,
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
      canOpenProfileSettings={canOpenProfileSettings}
      footer={<ChatInput onSend={(text) => handleSend(text)} status={status} />}
      onOpenProfileSettings={onOpenProfileSettings}
      onSignOut={onSignOut}
      profile={profile}
    />
  );
}

interface ChatPageLoaderProps {
  canOpenProfileSettings?: boolean;
  onAuthFailure: () => void;
  onOpenProfileSettings?: () => void;
  onSignOut?: () => void;
  profile: DisplayTwinProfile;
}

function ChatPageLoader({
  canOpenProfileSettings,
  onAuthFailure,
  onOpenProfileSettings,
  onSignOut,
  profile,
}: ChatPageLoaderProps) {
  const { createNewSession, error, initialMessages, isLoading, sessionId } =
    useSession();

  if (isLoading) {
    return (
      <ChatPageLoading
        canOpenProfileSettings={canOpenProfileSettings}
        onOpenProfileSettings={onOpenProfileSettings}
        onSignOut={onSignOut}
        profile={profile}
      />
    );
  }

  if (error || !sessionId) {
    return (
      <ChatPageError
        canOpenProfileSettings={canOpenProfileSettings}
        detail={error ?? strings.sessionUnavailable}
        onOpenProfileSettings={onOpenProfileSettings}
        onRetry={() => {
          void createNewSession();
        }}
        onSignOut={onSignOut}
        profile={profile}
      />
    );
  }

  return (
    <ChatPageInner
      canOpenProfileSettings={canOpenProfileSettings}
      initialMessages={initialMessages}
      key={sessionId}
      onAuthFailure={onAuthFailure}
      onOpenProfileSettings={onOpenProfileSettings}
      onSignOut={onSignOut}
      onSessionInvalidated={() => {
        void createNewSession();
      }}
      profile={profile}
      sessionId={sessionId}
    />
  );
}

export function ChatPage() {
  const { getAccessToken, signOut } = useUserAuth();
  const { isAuthenticated: isAdminAuthenticated } = useAuth();
  const [profile, setProfile] = useState<DisplayTwinProfile>(
    resolveFallbackProfile,
  );
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const avatarRevokeRef = useRef<(() => void) | null>(
    profile.avatarRevoke ?? null,
  );
  const canManageTwin = appConfig.adminMode && isAdminAuthenticated;

  useEffect(() => {
    if (
      avatarRevokeRef.current &&
      avatarRevokeRef.current !== profile.avatarRevoke
    ) {
      avatarRevokeRef.current();
    }
    avatarRevokeRef.current = profile.avatarRevoke ?? null;
  }, [profile.avatarRevoke]);

  useEffect(() => {
    return () => {
      avatarRevokeRef.current?.();
    };
  }, []);

  useEffect(() => {
    if (!canManageTwin && profileModalOpen) {
      setProfileModalOpen(false);
    }
  }, [canManageTwin, profileModalOpen]);

  const loadProtectedProfile = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      return resolveFallbackProfile();
    }

    const apiProfile = await getTwinProfile(accessToken);
    if (!apiProfile.name?.trim()) {
      return resolveFallbackProfile();
    }

    let avatarHandle: BlobUrlHandle | undefined;
    if (apiProfile.has_avatar) {
      try {
        avatarHandle = await getTwinAvatarUrl(accessToken);
      } catch {
        avatarHandle = undefined;
      }
    }

    return resolveApiProfile(apiProfile, avatarHandle);
  }, [getAccessToken]);

  useEffect(() => {
    let active = true;

    const loadProfile = async () => {
      try {
        const nextProfile = await loadProtectedProfile();
        if (!active) {
          nextProfile.avatarRevoke?.();
          return;
        }
        setProfile(nextProfile);
        return;
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
  }, [loadProtectedProfile]);

  return (
    <>
      <ChatPageLoader
        canOpenProfileSettings={canManageTwin}
        onAuthFailure={() => {
          void signOut();
        }}
        onOpenProfileSettings={
          canManageTwin
            ? () => {
                setProfileModalOpen(true);
              }
            : undefined
        }
        onSignOut={() => {
          void signOut();
        }}
        profile={profile}
      />

      {canManageTwin ? (
        <ProfileEditModal
          avatarUrl={profile.avatarUrl}
          hasAvatar={profile.hasAvatar}
          name={profile.name}
          onOpenChange={setProfileModalOpen}
          onRemoveAvatar={async () => {
            await deleteTwinAvatar();
            setProfile(await loadProtectedProfile());
          }}
          onSave={async (name) => {
            await updateTwinProfile(name);
            setProfile(await loadProtectedProfile());
          }}
          onUploadAvatar={async (file) => {
            await uploadTwinAvatar(file);
            setProfile(await loadProtectedProfile());
          }}
          open={profileModalOpen}
        />
      ) : null}
    </>
  );
}
