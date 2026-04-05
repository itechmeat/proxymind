## Purpose

Browser chat interface — layout, components, session management, error handling, responsive design. Introduced by S5-01.

## ADDED Requirements

### Requirement: Chat page layout

The chat page SHALL render a full-viewport-height (`h-dvh`) flex column with three sections: a fixed ChatHeader at the top, a scrollable MessageList filling remaining space, and a fixed ChatInput at the bottom. The layout SHALL be centered with a maximum content width suitable for reading.

#### Scenario: Page renders three-section layout

- **WHEN** the chat page loads
- **THEN** the page SHALL display a ChatHeader, a MessageList, and a ChatInput arranged vertically
- **AND** the total height SHALL equal the dynamic viewport height (`h-dvh`)

#### Scenario: MessageList fills available space

- **WHEN** the page is rendered
- **THEN** the MessageList SHALL expand (flex-1) to fill all vertical space between the header and input

---

### Requirement: ChatHeader displays twin identity

The ChatHeader SHALL display the twin's avatar and name. On mount, ChatPage SHALL fetch the twin profile from `GET /api/chat/twin`, which returns `{ name, has_avatar }`. ChatPage SHALL pass the resolved `name` and `has_avatar` to ChatHeader. When `has_avatar` is `true`, the avatar `<img>` element SHALL use `/api/chat/twin/avatar` as its `src` (the proxy endpoint). When `has_avatar` is `false`, the avatar SHALL fall back to displaying initials derived from the twin name.

The fallback chain for profile data SHALL be: API response, then environment variables (`VITE_TWIN_NAME`, `VITE_TWIN_AVATAR_URL`), then defaults ("ProxyMind", initials avatar). If the API call fails or returns incomplete data, the system SHALL fall back to env vars. For this story, incomplete data means the API profile object has no `name` value or only whitespace in `name`. If env vars are also absent, the system SHALL use defaults.

The ChatHeader SHALL render a Settings icon button (lucide-react `Settings` icon) in the right section of the header. The Settings button SHALL be rendered only when `import.meta.env.VITE_ADMIN_MODE === "true"`. When `VITE_ADMIN_MODE` is not `"true"` or is unset, the Settings button SHALL NOT be rendered. This is a UI-only guard -- it does not protect backend endpoints.

#### Scenario: Avatar from URL

- **WHEN** `VITE_TWIN_AVATAR_URL` is set to a valid image URL and the API is unavailable
- **THEN** the ChatHeader SHALL render an `img` element with that URL as the avatar

#### Scenario: Avatar fallback to initials

- **WHEN** the API is unavailable
- **AND** `VITE_TWIN_AVATAR_URL` is empty or not set
- **THEN** the ChatHeader SHALL render initials derived from `VITE_TWIN_NAME` as the avatar fallback

#### Scenario: Twin name displayed

- **WHEN** the ChatHeader renders
- **THEN** it SHALL display the twin name as text next to the avatar

#### Scenario: Profile loaded from API

- **WHEN** ChatPage mounts and `GET /api/chat/twin` returns `{ name: "Marcus Aurelius", has_avatar: true }`
- **THEN** the ChatHeader SHALL display "Marcus Aurelius" as the twin name
- **AND** the avatar `<img>` element SHALL have `src` set to the `/api/chat/twin/avatar` proxy endpoint

#### Scenario: API returns profile without avatar

- **WHEN** `GET /api/chat/twin` returns `{ name: "Marcus Aurelius", has_avatar: false }`
- **THEN** the ChatHeader SHALL display "Marcus Aurelius" as the twin name
- **AND** the avatar SHALL render initials derived from "Marcus Aurelius"

#### Scenario: API failure falls back to env vars

- **WHEN** `GET /api/chat/twin` fails with a network error or non-200 status
- **AND** `VITE_TWIN_NAME` is set to "Seneca"
- **THEN** the ChatHeader SHALL display "Seneca" as the twin name
- **AND** the avatar SHALL use `VITE_TWIN_AVATAR_URL` if set, or initials otherwise

#### Scenario: Full fallback to defaults

- **WHEN** `GET /api/chat/twin` fails
- **AND** `VITE_TWIN_NAME` is not set
- **THEN** the ChatHeader SHALL display "ProxyMind" as the twin name
- **AND** the avatar SHALL render initials derived from "ProxyMind"

#### Scenario: Settings button visible in admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` equals `"true"`
- **THEN** the ChatHeader SHALL render a Settings icon button (lucide-react) in the right section

#### Scenario: Settings button hidden when not admin

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset
- **THEN** the ChatHeader SHALL NOT render the Settings icon button

---

### Requirement: MessageList scrollable area with auto-scroll

The MessageList SHALL render messages inside a scrollable container. The component SHALL track whether the user is scrolled to the bottom. During streaming, the list SHALL auto-scroll to the bottom only if the user was already at the bottom before the new token arrived. When the user sends a message, the list SHALL always scroll to the bottom. When the user scrolls up (away from the bottom), auto-scroll SHALL stop and a floating "scroll to bottom" button SHALL appear.

#### Scenario: Auto-scroll during streaming at bottom

- **WHEN** the user is scrolled to the bottom and new streaming tokens arrive
- **THEN** the MessageList SHALL auto-scroll to keep the latest content visible

#### Scenario: Auto-scroll stops when user scrolls up

- **WHEN** the user scrolls up during streaming
- **THEN** auto-scroll SHALL stop
- **AND** a floating "scroll to bottom" button SHALL appear

#### Scenario: Scroll to bottom on user message send

- **WHEN** the user sends a new message
- **THEN** the MessageList SHALL scroll to the bottom regardless of previous scroll position

#### Scenario: Floating button scrolls to bottom

- **WHEN** the user clicks the "scroll to bottom" floating button
- **THEN** the MessageList SHALL scroll to the bottom
- **AND** the floating button SHALL disappear

---

### Requirement: MessageList empty state

When the session has no messages, the MessageList SHALL display an empty state visual (e.g., a welcome message or prompt). The empty state text SHALL come from the centralized strings module (`lib/strings.ts`).

#### Scenario: Empty state displayed

- **WHEN** the chat session has zero messages
- **THEN** the MessageList SHALL render an empty state element instead of message bubbles

---

### Requirement: MessageBubble rendering by role

User messages SHALL be right-aligned with an accent background and plain text content. Assistant messages SHALL be left-aligned with a neutral background, a small twin avatar on the left, and content rendered as Markdown via `react-markdown`. Both message types SHALL display a relative timestamp (e.g., "just now", "2m ago").

For assistant messages, the `react-markdown` plugin chain SHALL include the custom `remarkCitations` remark plugin, `rehypeRaw`, and `rehypeSanitize` (with a strict allowlist schema that allows only `sup` and `button[class, data-citation-index, aria-label, type]` for the citation markup). The plugin order SHALL be: `remarkCitations`, then `rehypeRaw`, then `rehypeSanitize`. The `remarkCitations` plugin SHALL treat citation markers as 1-based indices: `[source:1]` through `[source:N]` correspond to the first through Nth entries in the citations array. It SHALL find `[source:N]` patterns in text nodes and replace them with HTML nodes containing `<sup><button class="citation-ref" data-citation-index="N">N</button></sup>`. The `react-markdown` `components` prop SHALL map `button` elements with `className === "citation-ref"` to the `CitationRef` React component, rendering interactive superscript citation markers styled in indigo.

The replacement SHALL happen at render time only -- the raw text in `message.parts` SHALL NOT be mutated. The plugin SHALL apply only to assistant messages. User messages SHALL render as plain text (unchanged). Out-of-range markers (`[source:0]` or `[source:N]` where N exceeds the citations array length) SHALL be left as plain text. During streaming, `[source:N]` markers SHALL render as plain text until citations arrive via the SSE `citations` event, at which point a re-render SHALL replace them with interactive superscripts.

When an assistant message has non-empty `message.metadata.citations` and the message state is not `"streaming"`, a `CitationsBlock` component SHALL render below the message card, inside `MessageBubble`, after the card and before the meta section. Interactive `CitationRef` superscripts SHALL render only under the same two conditions: citations are populated and the message state is not `"streaming"`. When citations are empty or the message state is `"streaming"`, the `CitationsBlock` SHALL NOT render and citation markers SHALL remain plain text.

#### Scenario: User message appearance

- **WHEN** a message with `role: "user"` is rendered
- **THEN** the MessageBubble SHALL be right-aligned with accent styling and plain text content

#### Scenario: Assistant message Markdown rendering

- **WHEN** a message with `role: "assistant"` is rendered with Markdown content (e.g., bold, lists, code blocks)
- **THEN** the MessageBubble SHALL render the Markdown as formatted HTML via `react-markdown`
- **AND** the rendered HTML SHALL be sanitized by `rehype-sanitize` to prevent XSS

#### Scenario: Assistant message has twin avatar

- **WHEN** an assistant message is rendered
- **THEN** a small twin avatar SHALL appear to the left of the message bubble

#### Scenario: Relative timestamp displayed

- **WHEN** a message is rendered with a `created_at` timestamp
- **THEN** the MessageBubble SHALL display a human-readable relative time (e.g., "just now", "5m ago")

#### Scenario: Citation markers rendered as superscripts

- **WHEN** an assistant message contains `[source:1]` and `[source:2]` markers in its text
- **AND** `message.metadata.citations` contains at least 2 citations
- **AND** the message state is not `"streaming"`
- **THEN** each `[source:N]` marker SHALL be replaced with an interactive `CitationRef` superscript component displaying the number N
- **AND** the superscripts SHALL be styled in indigo

#### Scenario: Out-of-range citation markers left as plain text

- **WHEN** an assistant message contains `[source:0]` or `[source:5]` and the citations array has only 3 entries
- **THEN** the out-of-range markers SHALL be left as plain text and SHALL NOT be replaced with superscript components

#### Scenario: Citation markers during streaming render as plain text

- **WHEN** an assistant message has state `"streaming"` and contains `[source:1]` in partial text
- **AND** citations have not yet arrived via the SSE `citations` event
- **THEN** `[source:1]` SHALL render as plain text

#### Scenario: Citations re-render after SSE citations event

- **WHEN** the SSE `citations` event arrives and `message.metadata.citations` is populated
- **AND** the message state transitions from `"streaming"` to `"complete"`
- **THEN** all valid `[source:N]` markers SHALL be replaced with interactive `CitationRef` superscripts

#### Scenario: CitationsBlock rendered for cited assistant message

- **WHEN** an assistant message has non-empty `message.metadata.citations`
- **AND** the message state is not `"streaming"`
- **THEN** a `CitationsBlock` SHALL render below the message card and before the meta section

#### Scenario: CitationsBlock not rendered when no citations

- **WHEN** an assistant message has empty `message.metadata.citations`
- **THEN** the `CitationsBlock` SHALL NOT render

#### Scenario: CitationsBlock not rendered during streaming

- **WHEN** an assistant message has state `"streaming"`
- **THEN** the `CitationsBlock` SHALL NOT render, even if partial citation data exists

#### Scenario: Raw message text preserved

- **WHEN** citation markers are rendered as superscript components
- **THEN** the original text in `message.parts` SHALL NOT be mutated
- **AND** the raw `[source:N]` text SHALL be preserved for copy-to-clipboard and history

---

### Requirement: MessageBubble streaming state

During streaming, the assistant MessageBubble SHALL display a streaming indicator (animated dots or pulsing cursor) after the last received token. The indicator SHALL be visible only while the message status is "streaming".

#### Scenario: Streaming indicator visible during streaming

- **WHEN** an assistant message has status "streaming"
- **THEN** a StreamingIndicator SHALL be rendered after the message text

#### Scenario: Streaming indicator hidden after completion

- **WHEN** the assistant message status changes from "streaming" to "complete"
- **THEN** the StreamingIndicator SHALL no longer be rendered

---

### Requirement: MessageBubble partial state

When a message has status "partial" (server saved incomplete content on disconnect), the MessageBubble SHALL render the available text with a visual "incomplete" indicator. There SHALL NOT be a retry button for partial messages — the content is preserved as-is.

#### Scenario: Partial message rendered with indicator

- **WHEN** a message with `status: "partial"` is rendered
- **THEN** the MessageBubble SHALL display the message content
- **AND** a visual indicator SHALL signal that the message is incomplete
- **AND** no retry button SHALL be shown

---

### Requirement: MessageBubble failed state with retry

When a message has status "failed", the MessageBubble SHALL display an error message and a "Retry" button. Clicking "Retry" SHALL re-send the original user message as a new request with a new idempotency key.

#### Scenario: Failed message shows retry button

- **WHEN** a message with `status: "failed"` is rendered
- **THEN** the MessageBubble SHALL display an error indicator and a "Retry" button

#### Scenario: Retry sends new request

- **WHEN** the user clicks the "Retry" button on a failed message
- **THEN** the system SHALL send a new message request with a new idempotency key
- **AND** the failed message indicator SHALL be replaced by the new streaming response

---

### Requirement: ChatInput behavior

The ChatInput SHALL render a textarea with auto-resize (minimum 1 row, maximum approximately 5 rows) and a send button. Pressing **Enter** SHALL send the message. Pressing **Shift+Enter** SHALL insert a newline. The send button and Enter key SHALL be disabled when the input is empty (whitespace-only counts as empty). The ChatInput SHALL be disabled (textarea and send button) when the chat status is "submitted" or "streaming" to prevent duplicate sends.

#### Scenario: Enter sends message

- **WHEN** the user types text and presses Enter (without Shift)
- **THEN** the message SHALL be sent
- **AND** the input SHALL be cleared

#### Scenario: Shift+Enter inserts newline

- **WHEN** the user presses Shift+Enter
- **THEN** a newline SHALL be inserted in the textarea
- **AND** the message SHALL NOT be sent

#### Scenario: Empty input prevents send

- **WHEN** the textarea contains only whitespace or is empty
- **THEN** the send button SHALL be disabled
- **AND** pressing Enter SHALL NOT send a message

#### Scenario: Input disabled during streaming

- **WHEN** the chat status is "submitted" or "streaming"
- **THEN** the textarea and send button SHALL be disabled

#### Scenario: Textarea auto-resizes

- **WHEN** the user types multiple lines of text
- **THEN** the textarea SHALL grow vertically up to a maximum height (approximately 5 rows)

---

### Requirement: Session persistence via localStorage

The system SHALL persist the current session ID in `localStorage` under the key `proxymind_session_id`. On page load, if a session ID exists in localStorage, the system SHALL attempt to restore the session by calling `GET /api/chat/sessions/:id` with the current user's access token. If the backend returns 200, the session messages SHALL be loaded as initial chat history. If the backend returns 404 (session expired or invalid) or 403 (session belongs to a different user), the system SHALL create a new session via `POST /api/chat/sessions` and update localStorage. On user sign-out, the system SHALL clear `proxymind_session_id` from localStorage. On user sign-in, the system SHALL NOT restore a previous session — it SHALL create a new session for the authenticated user.

#### Scenario: Session restored from localStorage

- **WHEN** the page loads and `localStorage` contains a valid `proxymind_session_id`
- **AND** the backend returns 200 for `GET /api/chat/sessions/:id`
- **THEN** the chat SHALL render with the restored message history

#### Scenario: Expired session creates new session

- **WHEN** the page loads and `localStorage` contains a `proxymind_session_id`
- **AND** the backend returns 404 for that session
- **THEN** the system SHALL create a new session via `POST /api/chat/sessions`
- **AND** localStorage SHALL be updated with the new session ID

#### Scenario: Foreign session creates new session

- **WHEN** the page loads and `localStorage` contains a `proxymind_session_id`
- **AND** the backend returns 403 (session belongs to a different user)
- **THEN** the system SHALL create a new session via `POST /api/chat/sessions`
- **AND** localStorage SHALL be updated with the new session ID

#### Scenario: First visit creates new session

- **WHEN** the page loads and `localStorage` does not contain `proxymind_session_id`
- **THEN** the system SHALL create a new session via `POST /api/chat/sessions`
- **AND** the new session ID SHALL be saved to localStorage

#### Scenario: Sign-out clears session

- **WHEN** the user signs out
- **THEN** `proxymind_session_id` SHALL be removed from localStorage

#### Scenario: Sign-in starts fresh session

- **WHEN** a user signs in (regardless of whether localStorage contains a previous session ID)
- **THEN** the system SHALL create a new session for the authenticated user
- **AND** localStorage SHALL be updated with the new session ID

---

### Requirement: Chat route requires authentication

The chat page at `/` SHALL be wrapped in a `ProtectedRoute` component. If the user is not authenticated (no valid access token and silent refresh fails), the system SHALL redirect to `/auth/sign-in`. While the authentication state is loading (silent refresh in progress), the system SHALL display a loading indicator instead of the chat UI.

#### Scenario: Authenticated user sees chat

- **WHEN** an authenticated user navigates to `/`
- **THEN** the chat page SHALL render normally

#### Scenario: Unauthenticated user redirected to sign-in

- **WHEN** an unauthenticated user navigates to `/`
- **AND** silent refresh fails (no valid refresh token cookie)
- **THEN** the user SHALL be redirected to `/auth/sign-in`

#### Scenario: Loading state during silent refresh

- **WHEN** a user navigates to `/` and the silent refresh is in progress
- **THEN** the system SHALL display a loading indicator
- **AND** the chat UI SHALL NOT render until authentication resolves

---

### Requirement: History restoration on page refresh

After restoring a session with existing messages, the chat SHALL display all previous messages (both user and assistant) converted to the UI message format via the message adapter. The chat SHALL be fully interactive after history loads.

#### Scenario: Messages displayed after refresh

- **WHEN** the page refreshes and the session has 4 existing messages (2 user, 2 assistant)
- **THEN** all 4 messages SHALL be rendered in the MessageList in chronological order
- **AND** the ChatInput SHALL be enabled for new input

---

### Requirement: Responsive mobile-first layout

The chat layout SHALL be mobile-first and responsive. On small viewports (mobile), the chat SHALL fill the full screen width. On larger viewports, the content column SHALL be centered with appropriate max-width. The layout SHALL work correctly on all common viewport sizes.

#### Scenario: Mobile viewport fills screen

- **WHEN** the viewport width is 375px (mobile)
- **THEN** the chat layout SHALL fill the full screen width with no horizontal overflow

#### Scenario: Desktop viewport centers content

- **WHEN** the viewport width is 1440px (desktop)
- **THEN** the chat content column SHALL be centered with a maximum width constraint

---

### Requirement: Centralized UI strings

All user-facing text (button labels, placeholder text, empty state messages, error messages) SHALL be sourced from a centralized strings module (`lib/strings.ts`). No component SHALL contain hardcoded user-facing language strings. This ensures the interface is configurable per installation without modifying components, per the project's Product Language Policy.

#### Scenario: No hardcoded strings in components

- **WHEN** a component renders user-facing text (e.g., send button label, input placeholder, error message)
- **THEN** the text value SHALL be imported from `lib/strings.ts`
- **AND** no user-facing string literal SHALL appear directly in component JSX

---

### Requirement: Error UX for network and API failures

The chat UI SHALL handle the following error scenarios with appropriate user-facing feedback:

- **Network error** (fetch fails): Show error in the message bubble with a "Retry" button.
- **HTTP 409** (concurrent stream / idempotency conflict): Show an error message indicating "already processing" — this is a real rejection, not a silent duplicate.
- **HTTP 422** (no active snapshot): Show a "knowledge not ready" message.
- **SSE error event** mid-stream: Stop streaming and show error in the message bubble with a "Retry" button.
- **Connection lost** (heartbeat timeout): Show a "connection lost" indicator.

All error message strings SHALL come from `lib/strings.ts`.

#### Scenario: Network error shows retry

- **WHEN** a `fetch` call fails with a `TypeError` (network error)
- **THEN** the assistant message bubble SHALL display an error state with a "Retry" button

#### Scenario: 409 shows already processing error

- **WHEN** the backend responds with HTTP 409
- **THEN** the UI SHALL display an error message indicating the message is already being processed
- **AND** the error SHALL NOT be silently ignored

#### Scenario: 422 shows knowledge not ready

- **WHEN** the backend responds with HTTP 422
- **THEN** the UI SHALL display a "knowledge not ready" message to the user

#### Scenario: SSE error event mid-stream

- **WHEN** an `error` SSE event is received during streaming
- **THEN** streaming SHALL stop
- **AND** the message bubble SHALL show the error with a "Retry" button

#### Scenario: Connection lost indicator

- **WHEN** no SSE events (including heartbeats) are received within the expected timeout
- **THEN** a "connection lost" indicator SHALL be displayed

---

### Requirement: Test coverage for stable behavior

All stable UI behavior (session management, message rendering, input handling, error states, scroll behavior) MUST be covered by tests before archive, per Phase 5 requirements. CI tests SHALL be deterministic and SHALL NOT depend on external services.

#### Scenario: CI tests pass for all UI components

- **WHEN** `bun run test` is executed
- **THEN** all chat UI component and integration tests SHALL pass
- **AND** no test SHALL require a running backend or external network access
