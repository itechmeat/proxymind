# S5-01: Chat UI — Design Spec

## Story

> React + Vite + Bun. Chat interface: input field, message feed, SSE streaming, twin avatar and name.
>
> **Outcome:** visitor can chat with the twin in the browser
>
> **Verification:** open → send message → streaming response → history on refresh

**Parallel pair:** S4-04 (Query rewriting) — pure frontend vs pure backend, zero file overlap.

---

## Decisions

### Decided by discussion

| Decision | Choice | Rationale |
|----------|--------|-----------|
| CSS approach | shadcn/ui + Tailwind CSS | shadcn provides production-ready primitives (Button, Avatar, ScrollArea, Textarea) critical for Chat UI and Admin UI (S5-03). Tailwind is a hard dependency of shadcn. Custom components use per-component `.css` files alongside Tailwind utilities. |
| Visual style | Neutral modern (shadcn "new-york" defaults) | Clean zinc/slate palette, sharp lines. Standard for chat interfaces. Does not distract from content. Twin uniqueness comes from persona and knowledge, not visual gimmicks. Dark mode deferred. |
| Architecture | AI SDK `useChat` + custom `ProxyMindTransport` | AI SDK provides battle-tested streaming state management. Custom transport bridges our backend SSE format (meta/token/citations/done) to AI SDK's expected UI Message Stream format. |
| Component structure | Folder-per-component with dedicated `.css` file | Every custom component lives in its own folder with `.tsx`, `.css`, and `index.ts` — even if the CSS file is empty initially. shadcn components remain flat in `ui/`. |

### Decided as obvious (no discussion needed)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| State management | React 19 built-in (useState/useReducer/useContext) | YAGNI — Redux/Zustand unnecessary for a chat |
| Routing | React Router | S5-03 (Admin UI) adds pages; router needed from the start |
| Markdown rendering | react-markdown + rehype-sanitize | Standard for React; backend returns Markdown; rehype-sanitize prevents XSS |
| Session persistence | localStorage (session_id) + `GET /sessions/:id` on reload | Simplest path for "history on refresh" verification criterion |
| Responsive | Mobile-first | Chat is a classic mobile-first use case |
| Twin name/avatar | Env vars (`VITE_TWIN_NAME`, `VITE_TWIN_AVATAR_URL`) | YAGNI — S5-02 adds upload and profile metadata endpoint |
| Idempotency | `crypto.randomUUID()` per message send | Backend already supports `idempotency_key` |
| SSE client | `fetch` + `ReadableStream` (manual SSE parsing) | `EventSource` does not support POST; a library is unnecessary — SSE format is trivial |
| Auto-scroll | Scroll during streaming, stop on user scroll-up | Standard chat UX |
| Error UX | Retry button on failed messages, connection indicator | Backend distinguishes complete/partial/failed statuses |
| Testing | Vitest + React Testing Library | Matches spec.md (Vite ecosystem) |
| Chat layout | Full-page centered column (ChatGPT/Claude style) | Twin name + avatar in header, message feed center, input bottom |

---

## Dependencies

### New packages

| Package | Purpose |
|---------|---------|
| `ai` | AI SDK core — streaming utilities, types |
| `@ai-sdk/react` | `useChat` hook for React |
| `react-router` | Client-side routing (chat now, admin in S5-03) |
| `react-markdown` | Render assistant Markdown responses |
| `rehype-sanitize` | XSS protection for rendered Markdown |
| `tailwindcss` + `@tailwindcss/vite` | Tailwind CSS (required by shadcn) |

### Dev dependencies (testing)

| Package | Purpose |
|---------|---------|
| `vitest` | Test runner (Vite-native) |
| `@testing-library/react` | Component testing utilities |
| `@testing-library/jest-dom` | DOM assertion matchers |
| `happy-dom` | Lightweight DOM implementation for Vitest |

### shadcn/ui components (added via CLI)

`Button`, `Avatar`, `ScrollArea`, `Textarea` — added individually via `npx shadcn@latest add`.

### Setup steps

1. `bun add ai @ai-sdk/react react-router react-markdown rehype-sanitize`
2. `bun add -d tailwindcss @tailwindcss/vite`
3. `bun add -d vitest @testing-library/react @testing-library/jest-dom happy-dom`
4. Tailwind init — add `@import "tailwindcss"` to CSS entry, add plugin to `vite.config.ts`
5. Vitest config — create `vitest.config.ts` (or add `test` block to `vite.config.ts`) with `happy-dom` environment
6. `npx shadcn@latest init` — style: new-york, base color: zinc, CSS variables: yes
7. `npx shadcn@latest add button avatar scroll-area textarea`

### Environment variables

Addition to the existing `frontend/.env`:

```
VITE_TWIN_NAME=ProxyMind
VITE_TWIN_AVATAR_URL=
```

---

## Project Structure

```
frontend/src/
├── components/
│   ├── ui/                      ← shadcn components (flat, as CLI generates)
│   ├── ChatHeader/
│   │   ├── ChatHeader.tsx
│   │   ├── ChatHeader.css
│   │   └── index.ts
│   ├── ChatInput/
│   │   ├── ChatInput.tsx
│   │   ├── ChatInput.css
│   │   └── index.ts
│   ├── MessageBubble/
│   │   ├── MessageBubble.tsx
│   │   ├── MessageBubble.css
│   │   └── index.ts
│   ├── MessageList/
│   │   ├── MessageList.tsx
│   │   ├── MessageList.css
│   │   └── index.ts
│   └── StreamingIndicator/
│       ├── StreamingIndicator.tsx
│       ├── StreamingIndicator.css
│       └── index.ts
├── hooks/
│   └── useSession.ts            ← session create/restore/persist
├── lib/
│   ├── transport.ts             ← ProxyMindTransport (AI SDK custom transport)
│   ├── api.ts                   ← API client (createSession, getSession)
│   ├── sse-parser.ts            ← SSE event parsing from backend format
│   ├── message-adapter.ts       ← MessageInHistory ↔ AI SDK UIMessage mapping
│   ├── strings.ts               ← centralized UI strings (configurable per installation)
│   └── config.ts                ← env vars, constants
├── pages/
│   └── ChatPage/
│       ├── ChatPage.tsx
│       ├── ChatPage.css
│       └── index.ts
├── types/
│   └── chat.ts                  ← Session, Message, Citation, SSE event types
├── App.tsx                      ← React Router setup
├── main.tsx                     ← entry point
└── index.css                    ← global styles + tailwind import
```

### Conventions

- Every custom component — own folder with `.tsx`, `.css`, `index.ts` (re-export).
- shadcn components remain flat in `ui/` (as the CLI generates them).
- `lib/` — non-React code (transport, API, utilities).
- `hooks/` — custom React hooks.
- `pages/` — page-level components bound to a route.
- `types/` — shared TypeScript types.

### Dev CORS handling

In production, Caddy serves frontend and backend on the same origin (no CORS needed). In development, frontend runs on `:5173` (Vite) and backend on `:8000` (FastAPI) — different origins. To avoid CORS issues, configure Vite's `server.proxy` to forward `/api` requests to `http://localhost:8000`. This keeps the frontend code origin-agnostic (all requests go to relative `/api/...` paths). No CORS middleware is added to the backend.

### Internationalization (UI strings)

Per the project's Product Language Policy (CLAUDE.md), all UI labels must be configurable per installation — no hardcoded language. All user-facing strings are centralized in `lib/strings.ts` as a single record. This is not a full i18n framework (YAGNI), but it ensures strings are replaceable per deployment without hunting through components.

---

## SSE Transport Layer

### Architecture

```
useChat()
  │
  ▼
ProxyMindTransport
  ├── sendMessage(text, sessionId)
  │     ├── POST /api/chat/messages { session_id, text, idempotency_key }
  │     └── Returns stream of AI SDK-compatible events
  │
  └── parseSSEStream(response.body)
        ├── event: meta       → capture message_id, session_id, snapshot_id (metadata)
        ├── event: token      → emit text delta content
        ├── event: citations  → sideband storage (not part of text stream)
        ├── event: done       → emit finish signal
        ├── event: error      → emit error signal
        └── : heartbeat       → skip (keepalive)
```

### SSE parser (`sse-parser.ts`)

Stateless utility:

- Reads `ReadableStream<Uint8Array>` from fetch response.
- Parses SSE format (`event:` + `data:` lines, `\n\n` delimiter).
- Yields typed events: `MetaEvent | TokenEvent | CitationsEvent | DoneEvent | ErrorEvent`.
- Handles partial chunks (SSE data may arrive across chunk boundaries).

### SSE event payloads (from backend)

| Event | Payload fields |
|-------|---------------|
| `meta` | `message_id`, `session_id`, `snapshot_id` |
| `token` | `content` (string — one text delta) |
| `citations` | `citations` (array of citation objects) |
| `done` | `token_count_prompt`, `token_count_completion`, `model_name`, `retrieved_chunks_count` |
| `error` | `detail` (string) |

The transport captures `done` payload metadata (token counts, model name, chunk count) and stores it alongside the message. S5-01 does not display this data, but it is available for future debugging and cost tracking features.

### Citation sideband

Citations arrive as a separate SSE event after all tokens. The transport captures them via a callback (`onCitations`) but they are not part of the AI SDK text stream. They are stored alongside the message for S5-02 to display.

### Idempotency

Each `sendMessage` call generates `crypto.randomUUID()` as the idempotency key. Retry of a failed message creates a new request with a new key (new attempt = new key).

### AI SDK integration point

The transport integrates with AI SDK v6 via the `ChatTransport` interface (or equivalent hook point such as the `fetch` option on `useChat`). The exact integration surface depends on the AI SDK version available at implementation time — the implementer MUST verify the current AI SDK transport API from `@ai-sdk/react` docs before writing the adapter. This is a moderate technical risk: if the transport API is more constrained than expected, the fallback is Approach B (custom hook using AI SDK streaming utilities only, without `useChat`).

---

## Session Management

### `useSession` hook

Manages session lifecycle independently from `useChat`:

```
Page load
  │
  ├── localStorage has session_id?
  │     ├── YES → GET /api/chat/sessions/:id
  │     │          ├── 200 → convert messages to UIMessage[], return as initialMessages
  │     │          └── 404 → session expired/invalid, create new
  │     │
  │     └── NO → POST /api/chat/sessions → save id to localStorage
  │
  └── Ready: { sessionId, initialMessages, isReady }
```

**localStorage key:** `proxymind_session_id`

**Session creation request:** `POST /api/chat/sessions` with an empty body. The backend defaults to `channel: "web"` (see `CreateSessionRequest` in `chat_schemas.py`).

**"New chat" action:** Creates a new session, updates localStorage, resets `useChat` messages. Not in S5-01 scope but the hook supports it structurally.

### Message adapter (`message-adapter.ts`)

- `toUIMessages(messages: MessageInHistory[])` — converts backend history to AI SDK UIMessage format.
- Each message maps all relevant fields:
  - `id`, `role`, `createdAt` → direct mapping.
  - `content` → `parts: [{ type: 'text', text: content }]`.
  - `status` → determines rendering mode:
    - `complete` → normal rendered message.
    - `partial` → rendered text with a visual "incomplete" indicator (no retry — content is preserved).
    - `failed` → error state with "Retry" button.
  - `citations` → stored as custom annotation data on the message (available for S5-02).
  - `model_name` → stored as metadata (not displayed in S5-01).

---

## UI Components

### Page layout

```
┌──────────────────────────────┐
│ ChatHeader                   │  ← fixed top
│  [Avatar] Twin Name          │
├──────────────────────────────┤
│                              │
│ MessageList (ScrollArea)     │  ← flex-1, scrollable
│  ┌────────────────────────┐  │
│  │ User: "What is..."     │  │  ← right-aligned
│  └────────────────────────┘  │
│  ┌────────────────────────┐  │
│  │ Twin: "Based on..."    │  │  ← left-aligned + Avatar
│  │ [StreamingIndicator]   │  │
│  └────────────────────────┘  │
│                              │
├──────────────────────────────┤
│ ChatInput                    │  ← fixed bottom
│  [Textarea        ] [Send]   │
└──────────────────────────────┘
```

Full viewport height (`h-dvh`), flex column. Header and input are fixed; message list fills the remaining space.

### ChatHeader

- shadcn `Avatar` with `VITE_TWIN_AVATAR_URL` (fallback: initials from `VITE_TWIN_NAME`).
- Twin name next to the avatar.
- Minimal: no extra elements.

### MessageList

- shadcn `ScrollArea` wrapping a list of `MessageBubble` components.
- **Auto-scroll logic:**
  - Track `isAtBottom` via scroll event listener.
  - During streaming: auto-scroll only if `isAtBottom === true`.
  - User message sent: always scroll to bottom.
  - User scrolls up: stop auto-scroll, show "scroll to bottom" floating button.
- Ref on the scroll container for programmatic scrolling.

### MessageBubble

- **User message:** right-aligned, accent background, plain text.
- **Assistant message:** left-aligned, neutral background, small avatar on the left.
  - Content rendered via `react-markdown` + `rehype-sanitize`.
  - During streaming: shows `StreamingIndicator` after the last token.
  - On error/failed: shows error text and a "Retry" button.
- Relative timestamp ("just now", "2m ago").

### ChatInput

- shadcn `Textarea` with auto-resize (min 1 row, max ~5 rows).
- shadcn `Button` with send icon.
- **Enter** = send, **Shift+Enter** = newline.
- Disabled when chat is not ready for input. For Approach A (AI SDK `useChat`): `status === "submitted" || status === "streaming"` — this closes the gap between submit and first token that would otherwise allow duplicate sends. For Approach B: `status === "streaming"`.
- Empty input → send button disabled.

### StreamingIndicator

- Animated dots or pulsing cursor shown after the last streamed token.
- Visible only when `status === "streaming"`.

---

## Data Flow

### Sending a message (complete sequence)

1. User types in ChatInput, presses Enter.
2. ChatInput calls `sendMessage({ text })` from `useChat`. The component only provides the text — `session_id` (from the session hook) and `idempotency_key` (generated via `crypto.randomUUID()`) are injected by the transport automatically.
3. `useChat` optimistically adds the user message to `messages[]`.
4. `useChat` calls `ProxyMindTransport.sendMessage()`.
5. Transport POSTs to `/api/chat/messages`: `{ session_id, text, idempotency_key }`.
6. Backend begins SSE stream.
7. Transport receives and maps SSE events:
   - `event: meta` → stores `message_id` and `snapshot_id` as metadata.
   - `event: token` → maps to AI SDK text delta → `useChat` appends to assistant message.
   - `event: citations` → transport calls `onCitations` callback (stored for S5-02).
   - `event: done` → maps to AI SDK finish signal → `useChat` marks message complete.
8. UI re-renders on each token: MessageList shows growing assistant MessageBubble, StreamingIndicator is visible, auto-scroll is active.
9. Stream complete: StreamingIndicator hidden, ChatInput re-enabled, full Markdown rendered.

### Page reload (history restoration)

1. App loads → `useSession` reads `localStorage('proxymind_session_id')`.
2. If present → `GET /api/chat/sessions/:id`.
3. Response: session object with `messages[]` (both user and assistant).
4. `message-adapter` converts to `UIMessage[]` format.
5. `ChatPageLoader` renders `ChatPageInner` only after `isReady` — this avoids the React hooks ordering issue (hooks cannot be called conditionally, so `useChat` must not be invoked until session data is available). The wrapper pattern: `ChatPageLoader` calls `useSession`, renders loading state until ready, then mounts `ChatPageInner` which calls `useChat` with `initialMessages`.
6. Chat renders with full history.

---

## Error Handling

| Scenario | Detection | UX |
|----------|----------|-----|
| Network error (fetch fails) | `TypeError` from fetch | Error in message bubble, "Retry" button |
| Backend 404 (session not found) | HTTP 404 | Auto-create new session, show info message |
| Backend 409 (concurrent stream / idempotency conflict) | HTTP 409 | Show error: "Message already being processed". Backend returns 409 for both active concurrent stream and idempotency conflict while streaming — both are real rejections, not safe duplicates. |
| Backend 422 (no active snapshot) | HTTP 422 | Show "Knowledge base not ready" message |
| SSE `error` event | `event: error` in stream | Error text in bubble, "Retry" button |
| SSE timeout (no events) | Heartbeat timeout | "Connection lost" indicator, auto-retry once |
| Client disconnect during stream | `AbortController` | Backend saves partial response (server-side) |

### Retry logic

- Retry button on a failed message creates a **new** request with a **new** idempotency key.
- No automatic retries for send — user initiates.
- SSE connection drop: one automatic reconnect attempt, then show error.

---

## Testing Strategy

### Unit tests (Vitest)

| Target | What is tested |
|--------|---------------|
| `sse-parser.ts` | Parses SSE format correctly; handles partial chunks, heartbeats, malformed data |
| `message-adapter.ts` | Converts backend `MessageInHistory` ↔ AI SDK `UIMessage` format |
| `ProxyMindTransport` | Maps backend SSE events to AI SDK format (mock fetch) |
| `useSession` | Creates session on first visit; restores from localStorage; handles 404 gracefully |

### Component tests (Vitest + React Testing Library)

| Component | What is tested |
|-----------|---------------|
| `MessageBubble` | Renders user vs assistant styles; renders Markdown; shows error + retry button |
| `ChatInput` | Enter sends; Shift+Enter inserts newline; disabled during streaming; empty input validation |
| `MessageList` | Renders a list of messages; scroll container is present |
| `ChatHeader` | Shows avatar and twin name |

### Integration test (Vitest + React Testing Library)

| Test | Description |
|------|------------|
| `ChatPage` full flow | Mock transport → render page → type message → verify streaming renders → verify final message appears |

### Not tested in CI

- Real backend SSE connection (belongs to quality/evals track).
- Visual snapshot tests (not needed at this stage).

---

## Scope Boundaries

### In scope (S5-01)

- Chat layout: header, message list, input.
- SSE streaming via AI SDK `useChat` + custom `ProxyMindTransport`.
- Session creation and persistence (localStorage).
- History restoration on page refresh.
- Markdown rendering of assistant messages.
- Twin name and avatar display (from env vars).
- Basic error handling: retry, connection indicator.
- Responsive layout (mobile-first).

### Explicitly out of scope

| Feature | Story |
|---------|-------|
| Citation display (inline + collapsible block) | S5-02 |
| Twin avatar upload to SeaweedFS | S5-02 |
| Twin profile metadata form | S5-02 |
| Admin UI (sources, snapshots) | S5-03 |
| Dark mode toggle | Future |
| Typing indicator before first token | Nice-to-have, not in story |
| Message editing/deletion | Not planned |
| File/image upload in chat | Not planned |
