import { useEffect, useMemo, useRef, useState } from "react";

import { getSourceIcon } from "@/lib/source-icons";
import { strings } from "@/lib/strings";
import type { CitationResponse } from "@/types/chat";

import "./CitationsBlock.css";

export interface CitationHighlightRequest {
  citationIndex: number;
  token: number;
}

interface CitationsBlockProps {
  citations: CitationResponse[];
  expanded: boolean;
  highlightRequest?: CitationHighlightRequest | null;
  onExpandedChange?: (expanded: boolean) => void;
  onImageClick?: (citation: CitationResponse) => void;
}

export function CitationsBlock({
  citations,
  expanded,
  highlightRequest,
  onExpandedChange,
  onImageClick,
}: CitationsBlockProps) {
  const [highlightedCitationIndex, setHighlightedCitationIndex] = useState<
    number | null
  >(null);
  const itemRefs = useRef(new Map<number, HTMLLIElement>());

  const orderedCitations = useMemo(
    () => [...citations].sort((left, right) => left.index - right.index),
    [citations],
  );

  useEffect(() => {
    if (!expanded || !highlightRequest) {
      return;
    }

    const target = itemRefs.current.get(highlightRequest.citationIndex);
    if (!target) {
      return;
    }

    target.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
    setHighlightedCitationIndex(highlightRequest.citationIndex);

    const timeoutId = window.setTimeout(() => {
      setHighlightedCitationIndex((currentValue) =>
        currentValue === highlightRequest.citationIndex ? null : currentValue,
      );
    }, 1_000);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [expanded, highlightRequest]);

  if (citations.length === 0) {
    return null;
  }

  return (
    <section
      className="citations-block"
      aria-label={strings.sourcesCount(citations.length)}
    >
      <button
        aria-expanded={expanded}
        className="citations-block__toggle"
        onClick={() => {
          onExpandedChange?.(!expanded);
        }}
        type="button"
      >
        <span className="citations-block__toggle-icon" aria-hidden="true">
          {expanded ? "▼" : "▶"}
        </span>
        <span>{strings.sourcesCount(citations.length)}</span>
      </button>

      {expanded ? (
        <ol className="citations-block__list">
          {orderedCitations.map((citation) => {
            const { Icon, color } = getSourceIcon(citation.source_type);
            const isImageSource =
              citation.source_type === "image" && Boolean(citation.url);
            const isOnlineSource = Boolean(citation.url) && !isImageSource;

            return (
              <li
                key={`${citation.source_id}-${citation.index}`}
                className="citations-block__item"
                data-citation-index={citation.index}
                data-highlighted={
                  highlightedCitationIndex === citation.index ? "true" : "false"
                }
                ref={(element) => {
                  if (element) {
                    itemRefs.current.set(citation.index, element);
                    return;
                  }

                  itemRefs.current.delete(citation.index);
                }}
              >
                <span className="citations-block__index" aria-hidden="true">
                  {citation.index}
                </span>
                <Icon
                  aria-hidden="true"
                  className="citations-block__item-icon"
                  color={color}
                  size={18}
                />
                <div className="citations-block__body">
                  <p className="citations-block__label">
                    {isOnlineSource ? (
                      <a
                        className="citations-block__link"
                        href={citation.url ?? undefined}
                        rel="noopener noreferrer"
                        target="_blank"
                      >
                        {citation.source_title}
                      </a>
                    ) : isImageSource ? (
                      <button
                        className="citations-block__image-button"
                        onClick={() => {
                          onImageClick?.(citation);
                        }}
                        type="button"
                      >
                        {citation.source_title}
                      </button>
                    ) : (
                      <span>{citation.source_title}</span>
                    )}
                  </p>

                  {citation.url ? (
                    <span className="citations-block__url">{citation.url}</span>
                  ) : null}

                  {citation.text_citation ? (
                    <p className="citations-block__excerpt">
                      {citation.text_citation}
                    </p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}
