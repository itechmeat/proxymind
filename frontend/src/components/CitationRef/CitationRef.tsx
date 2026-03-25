import type { ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/utils";

import "./CitationRef.css";

interface CitationRefProps extends ComponentPropsWithoutRef<"button"> {
  citationIndex: number;
  onCitationClick?: (citationIndex: number) => void;
}

export function CitationRef({
  citationIndex,
  className,
  onCitationClick,
  onClick,
  type = "button",
  ...props
}: CitationRefProps) {
  return (
    <button
      {...props}
      className={cn("citation-ref", className)}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          onCitationClick?.(citationIndex);
        }
      }}
      type={type}
    />
  );
}
