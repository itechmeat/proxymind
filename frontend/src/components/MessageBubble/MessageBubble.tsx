import type { Element } from "hast";
import { useEffect, useState } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";

import { CitationRef } from "@/components/CitationRef";
import {
  type CitationHighlightRequest,
  CitationsBlock,
} from "@/components/CitationsBlock";
import { ImageLightbox } from "@/components/ImageLightbox";
import { StreamingIndicator } from "@/components/StreamingIndicator";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { citationSanitizeSchema } from "@/lib/citation-markdown";
import { getInitials } from "@/lib/identity";
import { getMessageText } from "@/lib/message-adapter";
import { remarkCitations } from "@/lib/remark-citations";
import { formatMessageError, formatRelativeTime, strings } from "@/lib/strings";
import type { ChatMessage } from "@/types/chat";

import "./MessageBubble.css";

interface MessageBubbleProps {
  message: ChatMessage;
  now?: Date;
  onRetry?: (messageId: string) => void;
  twinAvatarUrl?: string;
  twinName: string;
}

export function MessageBubble({
  message,
  now,
  onRetry,
  twinAvatarUrl,
  twinName,
}: MessageBubbleProps) {
  const text = getMessageText(message);
  const messageId = message.id;
  const state = message.metadata?.state ?? "complete";
  const isUser = message.role === "user";
  const citations = message.metadata?.citations ?? [];
  const [showAvatarImage, setShowAvatarImage] = useState(
    Boolean(twinAvatarUrl),
  );
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const [highlightRequest, setHighlightRequest] =
    useState<CitationHighlightRequest | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const timestamp = message.metadata?.createdAt
    ? formatRelativeTime(message.metadata.createdAt, now)
    : null;
  const showCitations =
    !isUser && state !== "streaming" && citations.length > 0;

  const markdownComponents: Components = {
    button({ children, className, node, ...props }) {
      const element = node as Element | undefined;
      const properties = element?.properties ?? {};
      const rawCitationIndex =
        properties.dataCitationIndex ?? properties["data-citation-index"];
      const citationIndex =
        typeof rawCitationIndex === "number"
          ? rawCitationIndex
          : Number.parseInt(String(rawCitationIndex ?? ""), 10);
      const normalizedClassName =
        typeof className === "string" ? className : undefined;

      if (
        normalizedClassName !== "citation-ref" ||
        !Number.isFinite(citationIndex)
      ) {
        return (
          <button {...props} className={normalizedClassName} type="button">
            {children}
          </button>
        );
      }

      return (
        <CitationRef
          {...props}
          citationIndex={citationIndex}
          className={normalizedClassName}
          onCitationClick={(selectedCitationIndex) => {
            setSourcesExpanded(true);
            setHighlightRequest((previousRequest) => ({
              citationIndex: selectedCitationIndex,
              token: (previousRequest?.token ?? 0) + 1,
            }));
          }}
        >
          {children}
        </CitationRef>
      );
    },
  };

  useEffect(() => {
    setShowAvatarImage(Boolean(twinAvatarUrl));
  }, [twinAvatarUrl]);

  useEffect(() => {
    if (!messageId) {
      return;
    }

    setSourcesExpanded(false);
    setHighlightRequest(null);
    setLightboxUrl(null);
  }, [messageId]);

  return (
    <article
      className={`message-bubble ${isUser ? "message-bubble--user" : "message-bubble--assistant"}`}
      data-role={message.role}
      data-state={state}
    >
      {!isUser ? (
        <Avatar className="message-bubble__avatar" size="sm">
          {twinAvatarUrl && showAvatarImage ? (
            <img
              alt={twinName}
              className="aspect-square size-full object-cover"
              onError={() => {
                setShowAvatarImage(false);
              }}
              src={twinAvatarUrl}
            />
          ) : null}
          {!showAvatarImage ? (
            <AvatarFallback>{getInitials(twinName)}</AvatarFallback>
          ) : null}
        </Avatar>
      ) : null}

      <div className="message-bubble__content">
        <div
          className={`message-bubble__card ${isUser ? "message-bubble__card--user" : "message-bubble__card--assistant"}`}
        >
          {isUser ? (
            <p className="message-bubble__text">{text}</p>
          ) : (
            <div className="message-bubble__markdown">
              <ReactMarkdown
                components={markdownComponents}
                rehypePlugins={[
                  rehypeRaw,
                  [rehypeSanitize, citationSanitizeSchema],
                ]}
                remarkPlugins={[
                  [
                    remarkCitations,
                    {
                      citations,
                      enabled: state !== "streaming",
                    },
                  ],
                ]}
              >
                {text}
              </ReactMarkdown>
              {state === "streaming" ? <StreamingIndicator /> : null}
            </div>
          )}

          {state === "failed" ? (
            <p className="message-bubble__error">
              {formatMessageError(message.metadata)}
            </p>
          ) : null}
        </div>

        {showCitations ? (
          <CitationsBlock
            citations={citations}
            expanded={sourcesExpanded}
            highlightRequest={highlightRequest}
            onExpandedChange={setSourcesExpanded}
            onImageClick={(citation) => {
              setLightboxUrl(citation.url);
            }}
          />
        ) : null}

        <div className="message-bubble__meta">
          {state === "partial" ? (
            <span className="message-bubble__badge">{strings.incomplete}</span>
          ) : (
            <span />
          )}
          {timestamp ? (
            <time
              className="message-bubble__timestamp"
              dateTime={message.metadata?.createdAt}
            >
              {timestamp}
            </time>
          ) : null}
        </div>

        {state === "failed" && onRetry ? (
          <div className="message-bubble__actions">
            <Button
              onClick={() => onRetry(message.id)}
              size="sm"
              type="button"
              variant="outline"
            >
              {strings.retry}
            </Button>
          </div>
        ) : null}
      </div>

      <ImageLightbox
        imageUrl={lightboxUrl}
        onOpenChange={(open) => {
          if (!open) {
            setLightboxUrl(null);
          }
        }}
        open={lightboxUrl !== null}
      />
    </article>
  );
}
