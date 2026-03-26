# S5-01: Chat UI — Tasks

Detailed implementation plan: `docs/superpowers/plans/2026-03-25-s5-01-chat-ui.md`

## 1. Project Setup

- [x] 1.1 Read `docs/development.md` and `docs/spec.md` before writing any code (mandatory pre-implementation step)
- [x] 1.2 Install runtime dependencies: `ai`, `@ai-sdk/react`, `react-router`, `react-markdown`, `rehype-sanitize`
- [x] 1.3 Install Tailwind CSS: `tailwindcss`, `@tailwindcss/vite`
- [x] 1.4 Install test dependencies: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `happy-dom`
- [x] 1.5 Configure Vite with Tailwind plugin and dev proxy (`/api` → `http://localhost:8000`)
- [x] 1.6 Create Vitest config with `happy-dom` environment and `passWithNoTests: true`
- [x] 1.7 Initialize shadcn/ui (style: new-york, base color: zinc, CSS variables: yes)
- [x] 1.8 Add shadcn components: `button`, `avatar`, `scroll-area`, `textarea`
- [x] 1.9 Replace `index.css` with Tailwind import + shadcn base styles
- [x] 1.10 Update `.env` and `.env.example`: change `VITE_API_URL` default to empty (relative paths via proxy), add `VITE_TWIN_NAME`, `VITE_TWIN_AVATAR_URL`
- [x] 1.11 Update `index.html` title to "ProxyMind"
- [x] 1.12 Remove old bootstrap assets (`App.css`, `assets/hero.png`, `vite.svg`, `react.svg`)
- [x] 1.13 Replace `App.tsx` with temporary placeholder
- [x] 1.14 Add `"test"` and `"test:watch"` scripts to `package.json`
- [x] 1.15 Verify `bun run build` succeeds and `bun run vitest run` exits cleanly

## 2. Types, Config, UI Strings, and API Client

- [x] 2.1 Create `src/types/chat.ts` with TypeScript types mirroring backend `chat_schemas.py`
- [x] 2.2 Create `src/lib/config.ts` with env vars (apiUrl as empty string for relative paths, twin name/avatar)
- [x] 2.3 Create `src/lib/strings.ts` with all centralized UI strings (including relative time format functions)
- [x] 2.4 Write failing tests for API client (`createSession`, `getSession`, 404 handling)
- [x] 2.5 Implement `src/lib/api.ts`
- [x] 2.6 Verify API client tests pass

## 3. SSE Parser

- [x] 3.1 Write failing tests: single event, multiple events, heartbeat skip, partial chunks, error event, citations event
- [x] 3.2 Implement `src/lib/sse-parser.ts` (async generator, ReadableStream → typed SSEEvent)
- [x] 3.3 Verify all SSE parser tests pass

## 4. Transport Layer (AI SDK Integration)

- [x] 4.1 **Spike: AI SDK transport API verification.** Read `@ai-sdk/react` official docs for `useChat`. Test whether a custom `ChatTransport` (or `fetch` override) can handle our SSE format. Write a finding document as a comment at the top of `transport.ts` covering: chosen integration point, exact param name for initial history (`messages` vs `initialMessages`), and status enum values. This spike determines whether Tasks 5–11 use UIMessage.parts (Approach A) or ChatMessage.content (Approach B).
- [x] 4.2 Decide Approach A (useChat + custom transport) vs Approach B (custom hook) based on spike findings
- [x] 4.2b **If Approach A chosen:** update `ChatMessage` type to wrap/extend `UIMessage`, update message adapter output to `UIMessage[]`, note that components will use `.parts` for text access and disable state checks `submitted || streaming` — per design ripple table in `design.md`
- [x] 4.3 Write failing tests: POST body, idempotency key generation, SSE-to-UI mapping, citations sideband, done metadata, error scenarios (409, 422, network failure, SSE mid-stream error)
- [x] 4.4 Implement `src/lib/transport.ts` (or `src/hooks/useProxyMindChat.ts` if Approach B)
- [x] 4.5 Verify all transport tests pass

## 5. Message Adapter

- [x] 5.1 Define `ChatMessage` UI type in `src/types/chat.ts` (adapt to UIMessage if Approach A)
- [x] 5.2 Write failing tests: complete message, "received" → "complete" mapping, partial status, failed status, citations preservation, empty array
- [x] 5.3 Implement `src/lib/message-adapter.ts` with `toUIMessages()` and status mapping
- [x] 5.4 Verify all message adapter tests pass

## 6. useSession Hook

- [x] 6.1 Write failing tests: new session creation, localStorage restore, 404 → new session, `createNewSession()`
- [x] 6.2 Implement `src/hooks/useSession.ts` with session lifecycle management
- [x] 6.3 Verify all useSession tests pass

## 7. ChatHeader and StreamingIndicator Components

- [x] 7.1 Write ChatHeader tests: renders name, renders avatar image, renders initials fallback
- [x] 7.2 Implement `src/components/ChatHeader/` (ChatHeader.tsx, ChatHeader.css, index.ts) using shadcn Avatar
- [x] 7.3 Implement `src/components/StreamingIndicator/` (animated dots, CSS animation)
- [x] 7.4 Verify ChatHeader tests pass

## 8. MessageBubble Component

- [x] 8.1 Write failing tests: user message rendering, assistant Markdown rendering, failed state with retry, partial state, streaming indicator, retry callback, relative timestamp
- [x] 8.2 Implement `src/components/MessageBubble/` with react-markdown + rehype-sanitize, all status states, relative time using `strings.ts`
- [x] 8.3 Verify all MessageBubble tests pass

## 9. ChatInput Component

- [x] 9.1 Write failing tests: Enter sends, Shift+Enter newline, empty input disabled, disabled prop, clears after send
- [x] 9.2 Implement `src/components/ChatInput/` with shadcn Textarea + Button, strings from `lib/strings.ts`
- [x] 9.3 Verify all ChatInput tests pass

## 10. MessageList Component

- [x] 10.1 Write failing tests: renders message list, empty state, scroll container present, scroll-to-bottom button appears when scrolled up
- [x] 10.2 Implement `src/components/MessageList/` with shadcn ScrollArea, auto-scroll logic, mandatory scroll-to-bottom button, empty state from `strings.ts`
- [x] 10.3 Verify all MessageList tests pass

## 11. ChatPage and Routing

- [x] 11.1 Implement `src/pages/ChatPage/` with ChatPageLoader/ChatPageInner wrapper pattern (avoids hooks ordering issue)
- [x] 11.2 Verify React Router import path for BrowserRouter (react-router vs react-router-dom)
- [x] 11.3 Update `App.tsx` with React Router — root route renders ChatPage
- [x] 11.4 Verify dev server renders the chat interface

## 12. Integration Tests

- [x] 12.1 Write integration test A: full chat flow — session init → send message → SSE streaming → response rendered
- [x] 12.2 Write integration test B: history restoration — localStorage session → GET returns messages → rendered on load
- [x] 12.3 Write integration test C: error 422 — send fails with "no active snapshot" → error displayed → retry button present
- [x] 12.4 Write integration test D: error 409 — concurrent send → "already processing" error displayed (not silently ignored)
- [x] 12.5 Write integration test E: connection lost — SSE stream drops mid-response → connection lost indicator shown → partial content preserved
- [x] 12.6 Verify all integration tests pass
- [x] 12.7 Run full test suite: `bun run test` — all tests pass

## 13. Final Verification and Cleanup

- [x] 13.1 Re-read `docs/development.md` and self-review all code against development standards
- [x] 13.2 Verify all installed package versions ≥ minimums in `docs/spec.md`
- [x] 13.3 Verify no hardcoded UI strings outside `lib/strings.ts`
- [x] 13.4 Verify `bun run build` succeeds (production build)
- [x] 13.5 Verify `bun run lint` passes (Biome)
- [x] 13.6 Run full test suite one final time
- [ ] 13.7 Manual smoke test (if backend running): send message → streaming → refresh → history restored → mobile viewport responsive
