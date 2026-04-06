import { useCallback, useEffect, useRef, useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { strings } from "@/lib/strings";
import type { ChatMessage } from "@/types/chat";

import "./MessageList.css";

interface MessageListProps {
  messages: ChatMessage[];
  onRetry?: (messageId: string) => void;
  twinAvatarUrl?: string;
  twinName: string;
}

const BOTTOM_OFFSET = 24;

export function MessageList({
  messages,
  onRetry,
  twinAvatarUrl,
  twinName,
}: MessageListProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const wasAtBottomRef = useRef(true);
  const showJumpButtonRef = useRef(false);
  const [showJumpButton, setShowJumpButton] = useState(false);

  const getViewport = useCallback(
    () =>
      rootRef.current?.querySelector<HTMLElement>(
        "[data-slot='scroll-area-viewport']",
      ),
    [],
  );

  const setJumpButtonVisible = useCallback((nextValue: boolean) => {
    if (showJumpButtonRef.current === nextValue) {
      return;
    }

    showJumpButtonRef.current = nextValue;
    setShowJumpButton(nextValue);
  }, []);

  const isSmoothScrollingRef = useRef(false);

  const cancelSmoothScroll = useCallback(() => {
    if (!isSmoothScrollingRef.current) {
      return;
    }
    isSmoothScrollingRef.current = false;
    const viewport = getViewport();
    if (viewport) {
      viewport.scrollTo({ top: viewport.scrollTop });
    }
  }, [getViewport]);

  const smoothScrollToBottom = useCallback(() => {
    const viewport = getViewport();
    if (!viewport) {
      return;
    }
    isSmoothScrollingRef.current = true;
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
  }, [getViewport]);

  const scrollToBottom = useCallback(() => {
    const viewport = getViewport();
    if (!viewport) {
      return;
    }

    viewport.scrollTop = viewport.scrollHeight;
    wasAtBottomRef.current = true;
    setJumpButtonVisible(false);
  }, [getViewport, setJumpButtonVisible]);

  useEffect(() => {
    const viewport = getViewport();
    if (!viewport) {
      return;
    }

    const syncScrollState = () => {
      const atBottom =
        viewport.scrollTop + viewport.clientHeight >=
        viewport.scrollHeight - BOTTOM_OFFSET;

      wasAtBottomRef.current = atBottom;
      if (atBottom) {
        isSmoothScrollingRef.current = false;
      }
      setJumpButtonVisible(!atBottom);
    };

    const onUserScroll = () => {
      cancelSmoothScroll();
    };

    syncScrollState();
    viewport.addEventListener("scroll", syncScrollState);
    viewport.addEventListener("wheel", onUserScroll, { passive: true });
    viewport.addEventListener("touchstart", onUserScroll, { passive: true });

    return () => {
      viewport.removeEventListener("scroll", syncScrollState);
      viewport.removeEventListener("wheel", onUserScroll);
      viewport.removeEventListener("touchstart", onUserScroll);
    };
  }, [getViewport, setJumpButtonVisible, cancelSmoothScroll]);

  useEffect(() => {
    const lastMessage = messages[messages.length - 1];

    if (!lastMessage) {
      return;
    }

    if (lastMessage.role === "user") {
      scrollToBottom();
    } else if (wasAtBottomRef.current) {
      smoothScrollToBottom();
    }
  }, [messages, smoothScrollToBottom, scrollToBottom]);

  return (
    <div className="message-list" ref={rootRef}>
      <ScrollArea
        aria-label={strings.conversationLabel}
        role="log"
        className="message-list__scroll"
      >
        <div className="message-list__viewport">
          {messages.length === 0 ? (
            <div className="message-list__empty">
              <div className="message-list__empty-card">
                <h2 className="message-list__empty-title">
                  {strings.emptyStateTitle}
                </h2>
                <p className="message-list__empty-body">
                  {strings.emptyStateBody}
                </p>
              </div>
            </div>
          ) : (
            <div className="message-list__stack">
              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  onRetry={onRetry}
                  twinAvatarUrl={twinAvatarUrl}
                  twinName={twinName}
                />
              ))}
            </div>
          )}
        </div>
      </ScrollArea>

      {showJumpButton ? (
        <Button
          className="message-list__jump"
          onClick={scrollToBottom}
          size="sm"
          type="button"
          variant="secondary"
        >
          {strings.scrollToBottom}
        </Button>
      ) : null}
    </div>
  );
}
