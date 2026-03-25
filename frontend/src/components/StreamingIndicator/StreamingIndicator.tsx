import { strings } from "@/lib/strings";

import "./StreamingIndicator.css";

export function StreamingIndicator() {
  return (
    <span
      aria-label={strings.streamingLabel}
      className="streaming-indicator"
      role="status"
    >
      <span className="streaming-indicator__dot" />
      <span className="streaming-indicator__dot" />
      <span className="streaming-indicator__dot" />
    </span>
  );
}
